import datetime
import re
import urllib.parse

def _convert_size(size):
    if type(size) is str and size.isdigit() or type(size) in [int, float]:
        return int(size)
    return 0


def _convert_ts(ts):
    ts_ = int(ts) if type(ts) is str and ts.isdigit() or type(ts) in [int, float] else 0
    return datetime.datetime.fromtimestamp(ts_)


class BaseAttributes:
    def __init__(self, properties):
        if type(properties) is dict:
            self.name = properties.get('name', '<not yet set>')
            self.id = properties.get('id', '')
            self.type = properties.get('type', '')
            if self.type not in ['file', 'folder']:
                self.type = 'transfer'
        else:
            print('?')
            print(properties)

    def matches(self, regex):
        return bool(regex.search(self.name))

    def __eq__(self, other):
        return hasattr(other, 'id') and self.id == other.id

    def to_data(self):
        return {'id': self.id, 'name': self.name, 'type': self.type}

    def __str__(self):
        return '{}: {}'.format(self.id, self.name)


class Folder(BaseAttributes):
    def __init__(self, properties):
        super().__init__(properties)

    def __str__(self):
        return '{s.name}: {s.id}'.format(s=self)
    

class File(BaseAttributes):
    def __init__(self, properties):
        super().__init__(properties)

        self.transcode_status = properties.get('transcode_status', '')
        self.link = properties.get('link', '')
        self.stream_link = properties.get('stream_link', '')

        self.created_at = _convert_ts(properties.get('created_at', 0))
        self.size = _convert_size(properties.get('size', 0))
        self.size_in_mb = int(self.size/1024/1024)

    def __str__(self):
        return '{s.id}: {s.name} ({s.size_in_mb}MB)'.format(s=self)


class Transfer(BaseAttributes):
    def __init__(self, properties):
        super().__init__(properties)
        self.size = _convert_size(properties.get('size', 0))
        self.size_in_mb = int(self.size/1024/1024)

        self.folder_id = properties.get('folder_id', '')
        self.file_id = properties.get('file_id', '')
        self.target_folder_id = properties.get('target_folder_id', '')

        self.status = properties.get('status', '')
        self.message = properties.get('message')

        self.ratio = properties.get('ratio', 0)
        self.progress = properties.get('progress', 0.0)
        self.leecher = properties.get('leecher')
        self.seeder = properties.get('seeder')
        self.speed_down = properties.get('speed_down')
        self.speed_up = properties.get('speed_up')
        self.eta = properties.get('eta')
        src_ = properties.get('src')
        self.src = TransferSrc(src_) if src_ else None

    def is_running(self):
        return self.status == 'queued' or self.status == 'running' or \
               (self.status == 'waiting' and self.status_msg() and
                not self.status_msg().startswith('Torrent did not finish for '))

    def status_msg(self):
        return self.status if self.status == 'finished' else "{}: {}".format(self.status, self.message)

    def __str__(self):
        return '{}: {}'.format(self.name, self.status_msg())


class Download:
    def __init__(self, properties, item):
        self.name = item.name + '.zip' if hasattr(item, 'name') else item
        self.link = properties.get('location', '')
        self.type = 'generated-zip' if hasattr(item, 'name') or self.link.endswith('.zip') else ''
        self.size = -1
        self.size_in_mb = -1

    def __str__(self):
        return '{s.name}'.format(s=self)


class TransferSrc:
    id = None
    name = None
    trackers = []

    def __init__(self, string_):
        id_re = re.match(r"^(magnet:.*?)(?=&|$)", string_)
        if id_re:
            self.id = id_re.group(0).upper() if id_re else None
            name_re = re.search(r"&dn=(.*?)(?=&|$)", string_)
            self.name = urllib.parse.unquote(name_re.group(1)) if name_re else None
            self.trackers = re.findall(r"&tr=(.*?)(?=&tr|$)", string_)
        if string_.startswith('https://www.premiumize.me/api/job/src'):
            self.id = re.search(r"(?<=\?id=)(.*?)(?=$)", string_).group(0)
