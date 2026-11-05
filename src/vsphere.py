"""Small, certificate-pinned vSphere SOAP client. No third-party dependencies."""
import hashlib
import http.client
import ssl
import threading
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

NS = {'v': 'urn:vim25', 's': 'http://schemas.xmlsoap.org/soap/envelope/'}


def endpoint(value):
    parsed = urlsplit(value.strip() if '://' in value else 'https://' + value.strip())
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter an IP address or hostname, optionally with an HTTPS port.')
    if parsed.path not in ('', '/', '/ui', '/ui/', '/sdk') or parsed.query or parsed.fragment:
        raise ValueError('Enter the server address, without a VM path or query.')
    host = parsed.hostname
    port = parsed.port or 443
    authority = ('[' + host + ']' if ':' in host else host) + (f':{port}' if port != 443 else '')
    return host, port, authority


def fingerprint(cert, algorithm='sha256'):
    digest = hashlib.new(algorithm, cert).hexdigest().upper()
    return ':'.join(digest[i:i+2] for i in range(0, len(digest), 2))


def probe(address):
    host, port, _ = endpoint(address)
    conn = http.client.HTTPSConnection(host, port, timeout=15, context=ssl._create_unverified_context())
    try:
        conn.connect()
        return conn.sock.getpeercert(binary_form=True)
    finally:
        conn.close()


class VSphere:
    def __init__(self, address, certificate):
        self.host, self.port, self.authority = endpoint(address)
        self.certificate = certificate
        self.cookie = ''
        self.refs = {}
        self.version = '6.0'
        self.lock = threading.RLock()
        self.product = ''

    def call(self, method, body):
        envelope = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                    f'<s:Body><{method} xmlns="urn:vim25">{body}</{method}></s:Body></s:Envelope>')
        with self.lock:
            conn = http.client.HTTPSConnection(self.host, self.port, timeout=30,
                                              context=ssl._create_unverified_context())
            try:
                conn.connect()
                if conn.sock.getpeercert(binary_form=True) != self.certificate:
                    raise RuntimeError('The server certificate changed. Disconnect and reconnect to review it.')
                headers = {'Content-Type': 'text/xml; charset=utf-8',
                           'SOAPAction': f'"urn:vim25/{self.version}"'}
                if self.cookie:
                    headers['Cookie'] = self.cookie
                conn.request('POST', '/sdk', envelope.encode('utf-8'), headers)
                response = conn.getresponse()
                data = response.read()
                cookie = response.getheader('Set-Cookie')
                if cookie:
                    self.cookie = cookie.split(';', 1)[0]
                try:
                    root = ET.fromstring(data)
                except ET.ParseError:
                    raise RuntimeError(f'Server returned HTTP {response.status}, rather than a vSphere API response.') from None
                fault = root.find('.//s:Fault', NS)
                if fault is not None:
                    raise RuntimeError(fault.findtext('faultstring') or 'vSphere rejected the request.')
                if response.status != 200:
                    raise RuntimeError(f'Server returned HTTP {response.status}.')
                return root
            finally:
                conn.close()

    def ref(self, name):
        kind, value = self.refs[name]
        return f'<_this type="{escape(kind)}">{escape(value)}</_this>'

    def login(self, username, password):
        root = self.call('RetrieveServiceContent', '<_this type="ServiceInstance">ServiceInstance</_this>')
        content = root.find('.//v:returnval', NS)
        for name in ('sessionManager', 'viewManager', 'propertyCollector', 'rootFolder'):
            node = content.find('v:' + name, NS)
            if node is None:
                raise RuntimeError(f'The server did not provide {name}.')
            self.refs[name] = (node.attrib['type'], node.text)
        self.product = content.findtext('v:about/v:fullName', '', NS)
        self.version = content.findtext('v:about/v:apiVersion', '6.0', NS)
        self.call('Login', self.ref('sessionManager') + f'<userName>{escape(username)}</userName>'
                  f'<password>{escape(password)}</password>')

    def inventory(self):
        kind, value = self.refs['rootFolder']
        root = self.call('CreateContainerView', self.ref('viewManager') +
                         f'<container type="{kind}">{escape(value)}</container>'
                         '<type>VirtualMachine</type><recursive>true</recursive>')
        view = root.find('.//v:returnval', NS).text
        try:
            paths = ('name', 'runtime.powerState', 'config.hardware.numCPU', 'config.hardware.memoryMB',
                     'config.template', 'config.files.vmPathName', 'config.hardware.device')
            body = self.ref('propertyCollector') + '<specSet><propSet><type>VirtualMachine</type>'
            body += ''.join(f'<pathSet>{p}</pathSet>' for p in paths)
            body += ('</propSet><objectSet><obj type="ContainerView">' + escape(view) + '</obj><skip>true</skip>'
                     '<selectSet xsi:type="TraversalSpec"><name>viewTraversal</name><type>ContainerView</type>'
                     '<path>view</path><skip>false</skip></selectSet></objectSet></specSet><options><maxObjects>200</maxObjects></options>')
            result = self.call('RetrievePropertiesEx', body)
            machines = []
            while True:
                for obj in result.findall('.//v:objects', NS):
                    props = {p.findtext('v:name', '', NS): p.find('v:val', NS)
                             for p in obj.findall('v:propSet', NS)}
                    text = lambda key, default='': props[key].text if key in props and props[key].text is not None else default
                    if text('config.template') == 'true':
                        continue
                    disks = 0
                    devices = props.get('config.hardware.device')
                    if devices is not None:
                        for device in devices:
                            if device.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}type', '').split(':')[-1] == 'VirtualDisk':
                                capacity = device.findtext('v:capacityInBytes', None, NS)
                                disks += int(capacity) if capacity else int(device.findtext('v:capacityInKB', '0', NS)) * 1024
                    machines.append({'id': obj.findtext('v:obj', '', NS), 'name': text('name'),
                                     'power': text('runtime.powerState', 'unknown'),
                                     'cpu': text('config.hardware.numCPU'), 'ram': text('config.hardware.memoryMB'),
                                     'path': text('config.files.vmPathName'), 'capacity': disks})
                token = result.findtext('.//v:token', '', NS)
                if not token:
                    break
                result = self.call('ContinueRetrievePropertiesEx', self.ref('propertyCollector') + f'<token>{escape(token)}</token>')
            return sorted(machines, key=lambda vm: vm['name'].casefold())
        finally:
            self.call('DestroyView', f'<_this type="ContainerView">{escape(view)}</_this>')

    def clone_ticket(self):
        return self.call('AcquireCloneTicket', self.ref('sessionManager')).findtext('.//v:returnval', '', NS)

    def properties(self, kind, ids, paths):
        """Read specific objects without creating a view or changing VM state."""
        body = self.ref('propertyCollector') + '<specSet><propSet><type>' + escape(kind) + '</type>'
        body += ''.join('<pathSet>' + escape(path) + '</pathSet>' for path in paths)
        body += '</propSet>'
        for value in ids:
            body += f'<objectSet><obj type="{escape(kind)}">{escape(value)}</obj></objectSet>'
        body += '</specSet><options/>'
        result = self.call('RetrievePropertiesEx', body)
        objects = {}
        while True:
            for obj in result.findall('.//v:objects', NS):
                missing_properties = obj.findall('v:missingSet', NS)
                if missing_properties:
                    faults = []
                    for missing in missing_properties:
                        path = missing.findtext('v:path', 'unknown property', NS)
                        fault = missing.find('v:fault/v:fault', NS)
                        fault_type = (fault.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}type', 'unknown fault')
                                      if fault is not None else 'unknown fault')
                        message = missing.findtext('v:fault/v:localizedMessage', '', NS)
                        faults.append(path + ' (' + fault_type.split(':')[-1] + ')' + (': ' + message if message else ''))
                    raise RuntimeError('The server could not return the VM/task cleanup properties: ' +
                                       kind + ' ' + obj.findtext('v:obj', '', NS) + ': ' + '; '.join(faults))
                objects[obj.findtext('v:obj', '', NS)] = {
                    prop.findtext('v:name', '', NS): prop.find('v:val', NS)
                    for prop in obj.findall('v:propSet', NS)}
            token = result.findtext('.//v:token', '', NS)
            if not token:
                break
            result = self.call('ContinueRetrievePropertiesEx', self.ref('propertyCollector') +
                               '<token>' + escape(token) + '</token>')
        if set(objects) != set(ids):
            raise RuntimeError('The VM or a recent task is unavailable; server cleanup cannot be checked.')
        return objects

    def export_readiness(self, vm_id, *, cleanup=False):
        """Check export eligibility separately from post-transfer power-on health."""
        paths = ('runtime.powerState', 'disabledMethod')
        if cleanup:
            paths += ('recentTask',)
        # Historical task objects can expire or be unreadable. Inspect them for
        # cleanup diagnostics, not as an additional permission requirement for
        # starting an export. ESXi still validates the actual ExportVm request.
        props = self.properties('VirtualMachine', [vm_id], paths)[vm_id]
        if props.get('runtime.powerState') is None:
            raise RuntimeError('The server omitted the VM power state needed to check export cleanup.')
        power = props['runtime.powerState'].text
        if power not in ('poweredOff', 'poweredOn', 'suspended'):
            raise RuntimeError('The server returned an unknown VM power state.')
        if not cleanup and power != 'poweredOff':
            return False, 'The VM must be powered off before export.'
        # Both arrays are optional in the API. With no missingSet error, an
        # omitted array means there are no entries, rather than a failed read.
        methods = props.get('disabledMethod', ())
        disabled = {node.text.rsplit('.', 1)[-1].lower() for node in methods if node.text}
        power_on_disabled = bool(disabled.intersection({'poweronvm_task', 'poweron'}))
        export_disabled = bool(disabled.intersection({'exportvm', 'export'}))
        if power == 'poweredOff' and (export_disabled or (cleanup and power_on_disabled)):
            labels = []
            if cleanup and power_on_disabled:
                labels.append('power-on')
            if export_disabled:
                labels.append('export')
            return False, 'The server currently disables ' + ' and '.join(labels) + ' for this VM.'
        tasks = [node.text for node in props.get('recentTask', ()) if node.text] if cleanup else []
        if tasks:
            for task in self.properties('Task', tasks, ('info.state', 'info.descriptionId')).values():
                if any(task.get(path) is None for path in ('info.state', 'info.descriptionId')):
                    raise RuntimeError('The server omitted a recent task state or description.')
                if task['info.state'].text in ('running', 'queued', 'pending') and 'export' in (task['info.descriptionId'].text or '').lower():
                    return False, 'The server still reports an export task in progress for this VM.'
        if not cleanup and power_on_disabled:
            return True, 'No export restriction was reported; power-on is disabled separately for this VM.'
        return True, 'No export restriction or active export task was reported by the server.'

    def fork(self):
        """Consume a ticket immediately; the new session survives browser logout."""
        with self.lock:
            child = VSphere(self.authority, self.certificate)
            child.refs = self.refs.copy()
            child.version = self.version
            child.product = self.product
            ticket = self.clone_ticket()
            if not ticket:
                raise RuntimeError('The server did not issue a session ticket.')
            child.call('CloneSession', child.ref('sessionManager') + f'<cloneTicket>{escape(ticket)}</cloneTicket>')
            return child

    def logout(self):
        if self.cookie and self.refs:
            try:
                self.call('Logout', self.ref('sessionManager'))
            except Exception:
                pass
        self.cookie = ''
