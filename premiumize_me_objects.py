import datetime

def _convert_size(size):
    if type(size) is str and size_.isdigit() or type(size) in [int, float]:
        return int(size)
    return 0

def _convert_ts(ts):
    ts_ = int(ts) if type(ts) is str and ts.isdigit() or type(ts) in [int, float] else 0
    return datetime.datetime.fromtimestamp(ts_)


class BaseAttributes:
    def __init__(self, properties):
        self.name = properties.get('name', '<not yet set>')
        self.id = properties.get('id', '')
        self.type = properties.get('type', '')

    def matches(self, regex):
        return bool(regex.search(self.name))

    def __eq__(self, other):
        return hasattr(other, 'id') and self.id == other.id

    def to_data(self):
        return {'id': self.id, 'name': self.name, 'type': self.type}


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


class Upload(BaseAttributes):
    def __init__(self, properties):
        super().__init__(properties)

    def __str__(self):
        return '{s.name}: {s.id}'.format(s=self)


class Transfer(BaseAttributes):
    def __init__(self, properties):
        super().__init__(properties)
        self.size = _convert_size(properties.get('size', 0))
        self.size_in_mb = int(self.size/1024/1024)

        self.hash = properties.get('hash', '')

        self.status = properties.get('status', '')
        self.message = properties.get('message')

        self.ratio = properties.get('ratio', 0)
        self.progress = properties.get('progress', 0.0)
        self.leecher = properties.get('leecher')
        self.seeder = properties.get('seeder')
        self.speed_down = properties.get('speed_down')
        self.speed_up = properties.get('speed_up')
        self.eta = properties.get('eta')

    def is_running(self):
        return self.status == 'queued' or \
               (self.status == 'waiting' and self.status_msg() and
                not self.status_msg().startswith('Torrent did not finish for '))

    def status_msg(self):
        return self.status if self.status != 'waiting' else self.message

    def __str__(self):
        return '{}: {}'.format(self.name, self.status_msg())


class Download:
    def __init__(self, properties):
        self.zip = properties.get('zip', '')
        content_keys = properties.get('content', {}).keys()
        self.name = list(content_keys)[0] if content_keys else ''

    def __str__(self):
        return '{s.name}'.format(s=self)
