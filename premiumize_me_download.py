#!/usr/bin/env python3
import datetime
import aiofiles
import aiohttp
import asyncio
import logging
import zipfile
import time
import json
import sys
import os
import re


class PremiumizeItem:
    def __init__(self, properties):
        try:
            self.error = properties.get('error', '')
            self.status = properties.get('status', '')
            self.message = properties.get('message')

            self.id = properties.get('id', '')
            self.hash = properties.get('hash', '')
            self.size = int(properties.get('size', 0))
            self.size_in_mb = int(self.size/1024/1024)
            self.name = properties.get('name', '')
            self.type = properties.get('type', '')

            self.created_at = datetime.datetime.fromtimestamp(int(properties.get('created_at', 0)))

            self.ratio = properties.get('ratio', 0)
            self.progress = properties.get('progress', 0.0)
            self.leecher = properties.get('leecher')
            self.seeder = properties.get('seeder')
            self.speed_down = properties.get('speed_down')
            self.speed_up = properties.get('speed_up')
            self.eta = properties.get('eta')
        except (ValueError, IndexError, AttributeError) as e:
            logging.error('Could not parse {}: {}'.format(self.__class__, e))
            del self
            return


class File(PremiumizeItem):
    def matches(self, regexes, hashes):
        return regexes.search(self.name) or self.hash in hashes

    def __str__(self):
        return '{s.id}: {s.name} ({s.size_in_mb}MB) {s.hash}'.format(s=self)


class Upload(PremiumizeItem):
    def __init__(self, url, properties):
        super().__init__(properties)
        self.url = url

    def worked(self):
        return self.status == 'success' and not self.error

    def __str__(self):
        return '{s.name}: {s.hash}'.format(s=self) if self.worked() else '{}:\t{}'.format(self.url, self.error)


class Transfer(PremiumizeItem):
    def is_running(self):
        return self.status == 'waiting'

    def status_msg(self):
        return self.status if self.status != 'waiting' else self.message

    def __str__(self):
        return '{}: {}'.format(self.name, self.status_msg())


class PremiumizeMeDownloader:
    url = 'https://www.premiumize.me/api'

    def __init__(self, download_directory, auth, event_loop, delete_after_download_days=0):
        logging.getLogger("requests").setLevel(logging.WARNING)
        self.delete_after = datetime.timedelta(days=delete_after_download_days)
        self.download_directory = download_directory

        self.event_loop = event_loop
        self.max_simultaneous_downloads = asyncio.Semaphore(2)
        self.aiohttp_session = None

        self.username, self.password = self._read_auth(auth)
        self.login_data = {'customer_id': self.username, 'pin': self.password}

    def close(self):
        self.aiohttp_session.close()

    @staticmethod
    def _parse_filters(filters):
        hashes = [f for f in filters if re.match(r'[0-9a-fA-F]{40}$', f)]
        regexes = re.compile('|'.join(r for r in filters if r not in hashes), re.IGNORECASE)
        return regexes, hashes

    async def download_files(self, filters):
        now = datetime.datetime.now()
        regexes, hashes = self._parse_filters(filters)
        files_deleted = []
        file_list = await self.get_list_of_files()
        for file_ in file_list:
            if file_.matches(regexes, hashes):
                success = await self._download_file(file_)
                if success and self.delete_after and file_.created_at+self.delete_after < now:
                    await self.delete(file_)
                    files_deleted.append(file_)

        if self.delete_after:
            [file_list.remove(d) for d in files_deleted]
            logging.info('Remaining files in "My Files":  {}'.format([str(f) for f in file_list]))

    async def get_list_of_files(self):
        ret = await self._make_request('/folder/list')
        ret_j = json.loads(ret)
        if 'error' in ret_j:
            logging.error('Error while getting file-list. Was: {}'.format(ret_j.get('message')))
            return []

        return [File(properties_) for properties_ in ret_j.get('content', []) if properties_]

    async def get_transfers(self):
        ret = await self._make_request('/transfer/list')
        ret_j = json.loads(ret)
        if 'error' in ret_j:
            logging.error('Error while getting file-list. Was: {}'.format(ret_j.get('message')))
            return []

        return [Transfer(properties_) for properties_ in ret_j.get('transfers', []) if properties_]

    async def _download_file(self, file_):
        path_ = os.path.join(self.download_directory, file_.name)
        if os.path.exists(path_):
            try:
                if file_.size * 0.999 < self._get_size(path_) < file_.size * 1.001:
                    logging.info('Skipped "{}",get already exists'.format(file_.name))
                    return True
            except OSError as e:
                logging.warning('Could not get size of file "{}": {}'.format(file_.name, e))

        ret = await self._make_request('/torrent/browse', params={'hash': file_.hash})
        ret_j = json.loads(ret)

        zip_dl_link = ret_j.get('zip', '')
        if not zip_dl_link or ret_j.get('status', '') == 'error':
            logging.warning('Could not download file "{}": {}'.format(file_.name, ret_j.get('message', '')))
            return False

        logging.info('Downloading {} ({} MB)...'.format(file_.name+'.zip', file_.size_in_mb))
        return await self.download_file(file_, zip_dl_link)

    async def download_file(self, file_, link):
        async with self.max_simultaneous_downloads:
            start_time = time.time()
            async with self.aiohttp_session.get(link, data=self.login_data) as response:
                file_destination = os.path.join(self.download_directory, file_.name + '.zip')
                if response.status == 200:
                    async with aiofiles.open(file_destination, 'wb') as f:
                        while True:
                            chunk = await response.content.read(512)
                            if not chunk:
                                break
                            await f.write(chunk)

                    self._unzip(file_destination)

                    transfer_time = time.time() - start_time
                    logging.info('Download finished, took {:.5}s, at {:.4}MByte/s'.format(
                        transfer_time, file_.size_in_mb / transfer_time))
                    return True
                else:
                    logging.error('Download of "{}" failed, returned "{}"!'.format(link, response.status))
                    return False

    def _unzip(self, file_destination):
        try:
            z = zipfile.ZipFile(file_destination)
            z.extractall(path=self.download_directory)
            os.remove(file_destination)
        except zipfile.error as e:
            logging.warning('Unzipping of "{}" failed: {}'.format(file_destination, e))

    async def delete(self, item_):
        if not item_.id:
            return True
        ret = await self._make_request('/item/delete', params={'type': item_.type, 'id': item_.id})
        if 'success' in ret:
            return True
        logging.error('Could not delete file {}: {}'.format(item_, ret))

    async def _make_request(self, url, data=None, params=None):
        """ Do a request, take care of the cookies, timeouts and exceptions """
        data_ = self.login_data
        if data is not None:
            data_.update(data)
        if params is None:
            params = {}
        if self.aiohttp_session is None:
            self.aiohttp_session = aiohttp.ClientSession(loop=self.event_loop)

        retries = 3
        for _ in range(retries):
            try:
                async with self.aiohttp_session.post(self.url + url, data=data_,
                                                     params=params, timeout=2) as r_:
                    text = await r_.text()
                    if r_.status == 200:
                        return text
            except (aiohttp.errors.TimeoutError, aiohttp.errors.ClientConnectionError):
                await asyncio.sleep(1)
            except Exception as e:
                logging.debug('Caught Exception "{}" while making a get-request to "{}"'.format(e.__class__, url))
                return json.dumps({'error':'true', 'message': str(e)})
        return json.dumps({'error':'true', 'message': 'timeout'})

    def _get_size(self, path_):
        if not os.path.isdir(path_):
            return os.path.getsize(path_)
        return sum(self._get_size(entry.path) for entry in os.scandir(path_))

    @staticmethod
    def _read_auth(auth):
        if auth and os.path.exists(auth):
            with open(auth, 'r') as f:
                auth = f.read()

        if not (auth and ':' in auth):
            logging.error('No ":" found in authentication information, login not possible!')
            return None, None

        username, password = auth.strip().split(':')
        return username, password

    async def upload(self, torrent):
        ret = await self._make_request("/transfer/create", params={'type': 'torrent', 'src': torrent})
        return Upload(torrent, json.loads(ret))

    async def upload_files(self, torrents):
        download_ids = [asyncio.ensure_future(self.upload(torrent)) for torrent in torrents]
        responses = await asyncio.gather(*download_ids)

        logging.info('Ids of uploaded files:')
        logging.info('\n'.join(map(str, responses)))
        return responses

    def __bool__(self):
        return bool(self.username and self.password)


if __name__ == '__main__':
    import argparse
    from os import path, access, W_OK, R_OK

    def argcheck_dir(string):
        if path.isdir(string) and access(string, W_OK) and access(string, R_OK):
            return path.abspath(string)
        raise argparse.ArgumentTypeError('{} is no directory or isn\'t writeable'.format(string))

    def argcheck_re(string):
        try:
            re.compile(string)
            return string
        except re.error:
            raise argparse.ArgumentTypeError('{} is no valid regular expression!'.format(string))

    argparser = argparse.ArgumentParser(description="Download your files at premiumize.me")
    argparser.add_argument('files', nargs='+', type=argcheck_re,
                           help='Download all files matching these (python) regular expressions.')
    argparser.add_argument('download_directory', type=argcheck_dir, default='.',
                           help='Set the directory to download the file(s) into.')
    argparser.add_argument('-a', '--auth', type=str, required=True,
                           help="Either 'user:password' or a path to a pw-file with that format")
    argparser.add_argument('-d', '--delete_after_download_days', type=int, default=0,
                           help="Delete files from My Files after successful download")
    argparser.add_argument('-u', '--upload', action='store_true',
                           help="Don't download files, but upload the given files")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s',
                        level=logging.INFO)

    event_loop = asyncio.get_event_loop()
    dl = PremiumizeMeDownloader(args.download_directory, args.auth, event_loop,
                                delete_after_download_days=args.delete_after_download_days)
    if not dl:
        sys.exit(1)

    try:
        if args.upload:
            event_loop.run_until_complete(dl.upload_files(args.files))
        else:
            event_loop.run_until_complete(dl.download_files(args.files))
    except KeyboardInterrupt:
        pass
    finally:
        dl.close()
        event_loop.close()
