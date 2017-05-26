import os
import json
import time
import logging
import aiofiles
import aiohttp
import asyncio
import zipfile
import subprocess
import concurrent.futures

from premiumize_me_dl.premiumize_me_objects import Transfer, Torrent, Upload, File


class PremiumizeMeAPI:
    url = 'https://www.premiumize.me/api'
    USE_NATIVE_DOWNLOADER = False

    def __init__(self, auth, event_loop):
        self.username, self.password = self._read_auth(auth)
        self.login_data = {'customer_id': self.username, 'pin': self.password}

        self.file_list_cached = None
        self.event_loop = event_loop

        self.max_simultaneous_downloads = asyncio.Semaphore(2)
        if not self.USE_NATIVE_DOWNLOADER:
            self.process_pool = concurrent.futures.ThreadPoolExecutor(4)
        self.aiohttp_session = None

    def close(self):
        if self.aiohttp_session is not None:
            self.aiohttp_session.close()

    async def download_file(self, file_, download_directory):
        if self._file_exists(file_, download_directory):
            return True

        torrent = await self.get_torrent_from_file(file_)

        async with self.max_simultaneous_downloads:
            logging.info('Downloading {} ({} MB)...'.format(file_.name, file_.size_in_mb))

            file_destination = os.path.join(download_directory, torrent.name + '.zip')
            if self.USE_NATIVE_DOWNLOADER:
                return await self.download_file_native(file_, torrent, file_destination)
            else:
                return await self.download_file_wget(torrent, file_destination)

    async def download_file_wget(self, torrent, file_destination):
        proc = await self.event_loop.run_in_executor(self.process_pool,
                                                     self._download_file_wget_process, torrent, file_destination)
        return await proc.result()

    def _download_file_wget_process(self, torrent, file_destination):
        proc = subprocess.run(['wget', torrent.zip, '-qO', file_destination, '--show-progress'])
        if proc == 0:
            self._unzip(file_destination)
            return True
        else:
            return False

    async def download_file_native(self, file_, torrent, file_destination):
        start_time = time.time()
        async with self.aiohttp_session.get(torrent.zip, data=self.login_data) as response:
            if response.status == 200:
                async with aiofiles.open(file_destination, 'wb') as f:
                    while True:
                        try:
                            chunk = await response.content.read(8192)
                        except concurrent.futures.TimeoutError:
                            pass
                        if not chunk:
                            break
                        await f.write(chunk)

                self._unzip(file_destination)

                transfer_time = time.time() - start_time
                logging.info('Download finished, took {}s, at {:.4}MByte/s'.format(
                    int(transfer_time), file_.size_in_mb / transfer_time))
                return True
            else:
                logging.error('Download of "{}" failed, returned "{}"!'.format(torrent.name, response.status))
                return False

    async def upload(self, torrent):
        src = None
        if type(torrent) is str:
            src = torrent

        response_text = await self._make_request("/transfer/create", params={'type': 'torrent', 'src': src})
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = None
            return Upload(response_json)
        logging.error('Could not upload torrent {}: {}'.format(torrent, response_json.get('message')))
        return None

    async def delete(self, file_):
        if not file_ or not file_.id:
            return True
        response_text = await self._make_request('/item/delete', params={'type': file_.type, 'id': file_.id})
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = None
            return True
        logging.error('Could not delete file {}: {}'.format(file_, response_json.get('message')))
        return False

    async def get_file_from_transfer(self, transfer_):
        if not self.file_list_cached:
            await self.get_files()
        for file_ in self.file_list_cached:
            if file_.hash == transfer_.hash:
                return file_

        logging.error('No file for transfer "{}" found'.format(transfer_.name))

    async def get_torrent_from_file(self, file_):
        response_text = await self._make_request('/torrent/browse', params={'hash': file_.hash})
        success, response_json = self._validate_to_json(response_text)
        if success:
            return Torrent(response_json)

        logging.error('Could not download file "{}": {}'.format(file_.name, response_json.get('message', '?')))

    async def get_files(self):
        if self.file_list_cached is not None:
            return self.file_list_cached
        response_text = await self._make_request('/folder/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = [File(properties_) for properties_ in response_json.get('content', []) if properties_]
            return self.file_list_cached
        logging.error('Error while getting files. Was: {}'.format(response_json.get('message')))
        return []

    async def get_transfers(self):
        response_text = await self._make_request('/transfer/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            return [Transfer(properties_) for properties_ in response_json.get('transfers', []) if properties_]
        logging.error('Error while getting transfers. Was: {}'.format(response_json.get('message')))
        return []

    async def _make_request(self, url, data=None, params=None):
        """ Do a request, take care of the login, timeouts and exceptions """
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
                                                     params=params, timeout=10) as r_:
                    text = await r_.text()
                    if r_.status == 200:
                        return text
            except (aiohttp.errors.TimeoutError, aiohttp.errors.ClientConnectionError):
                await asyncio.sleep(1)
            except Exception as e:
                logging.debug('Caught Exception "{}" while making a get-request to "{}"'.format(e.__class__, url))
                return json.dumps({'error': 'true', 'message': str(e)})
        return json.dumps({'error': 'true', 'message': 'timeout'})

    @staticmethod
    def _validate_to_json(response_text):
        response_json = json.loads(response_text)
        if response_json.get('status') == 'error':
            return False, response_json
        return True, response_json

    @staticmethod
    def _unzip(file_destination):
        try:
            z = zipfile.ZipFile(file_destination)
            z.extractall(path=os.path.dirname(file_destination))
            os.remove(file_destination)
        except zipfile.error as e:
            logging.warning('Unzipping of "{}" failed: {}'.format(file_destination, e))

    def _file_exists(self, file_, directory):
        path_ = os.path.join(directory, file_.name)
        if os.path.exists(path_):
            try:
                if file_.size and file_.size * 0.999 < self._get_size(path_) < file_.size * 1.001:
                    logging.info('Skipped "{}", already exists'.format(file_.name))
                    return True
            except OSError as e:
                logging.warning('Could not get size of file "{}": {}'.format(file_.name, e))
        return False

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

    def __bool__(self):
        return bool(self.username and self.password)
