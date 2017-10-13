import datetime


class HasSize:
    def __init__(self, size_):
        self.size = int(size_) if type(size_) is str and size_.isdigit() else 0
        self.size_in_mb = int(self.size/1024/1024)


class File(HasSize):
    def __init__(self, properties):
        super().__init__(properties.get('size', 0))

        self.name = properties.get('name', '')
        self.id = properties.get('id', '')
        self.type = properties.get('type', '')
        self.hash = properties.get('hash', '')
        ts_ = properties.get('created_at', 0)
        ts = int(ts_) if type(ts_) is str and ts_.isdigit() else 0
        self.created_at = datetime.datetime.fromtimestamp(ts)

    def matches(self, regex, hashes):
        return bool(regex.search(self.name)) or self.hash in hashes

    def __str__(self):
        return '{s.id}: {s.name} ({s.size_in_mb}MB) {s.hash}'.format(s=self)


class Upload:
    def __init__(self, properties):
        self.name = properties.get('name', '')
        self.id = properties.get('id', '')
        self.type = properties.get('type', '')

    def __str__(self):
        return '{s.name}: {s.id}'.format(s=self)


class Transfer(HasSize):
    def __init__(self, properties):
        super().__init__(properties.get('size', 0))

        self.name = properties.get('name', None)
        if self.name is None:
            self.name = '<not yet set>'
        self.id = properties.get('id', '')
        self.hash = properties.get('hash', '')

        self.status = properties.get('status', '')
        self.message = properties.get('message')
        self.type = properties.get('type', '')

        self.ratio = properties.get('ratio', 0)
        self.progress = properties.get('progress', 0.0)
        self.leecher = properties.get('leecher')
        self.seeder = properties.get('seeder')
        self.speed_down = properties.get('speed_down')
        self.speed_up = properties.get('speed_up')
        self.eta = properties.get('eta')

    def is_running(self):
        return self.status == 'queued' or \
               self.status == 'waiting' and not self.status_msg().startswith('Torrent did not finish for ')

    def status_msg(self):
        return self.status if self.status != 'waiting' else self.message

    def __str__(self):
        return '{}: {}'.format(self.name, self.status_msg())


class Torrent(HasSize):
    def __init__(self, properties):
        super().__init__(properties.get('size', 0))

        self.zip = properties.get('zip', '')
        content_keys = properties.get('content', {}).keys()
        self.name = list(content_keys)[0] if content_keys else ''

    def __str__(self):
        return '{s.name}: {s.size_in_mb}MB'.format(s=self)
