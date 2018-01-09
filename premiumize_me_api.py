import os
import json
import time
import logging
import aiohttp
import asyncio
import zipfile
import getpass
import subprocess
import concurrent.futures

from premiumize_me_dl.premiumize_me_objects import Transfer, Download, Upload, File, Folder

# Premiumize.me API Version
__version__ = 3


class PremiumizeMeAPI:
    url = 'https://www.premiumize.me/api'

    def __init__(self, auth, event_loop=None):
        self.event_loop = asyncio.get_event_loop() if event_loop is None else event_loop
        self.login_data = self._read_auth(auth)

        self.file_list_cached = None
        self.aiohttp_session = None

        self.max_simultaneous_downloads = asyncio.Semaphore(2)
        self.process_pool = concurrent.futures.ThreadPoolExecutor(4)

    def close(self):
        if self.aiohttp_session is not None:
            self.aiohttp_session.close()

    async def wait_for_torrent(self, upload_):
        #TODO: Test after API-Change
        logging.info('Waiting for premiumize.me to finish downloading the torrent...')
        transfer = None
        while transfer is None or transfer.is_running() and transfer.status != 'error':
            await asyncio.sleep(2)

            for transfer_ in await self.get_transfers():
                if transfer_.id == upload_.id:
                    transfer = transfer_
            logging.info('  Status: {}'.format(transfer.status_msg()))
        return transfer

    async def download_file(self, file_, download_directory):
        if self._file_exists(file_, download_directory):
            return True

        download = await self.get_file_download(file_)
        if not download:
            return 

        async with self.max_simultaneous_downloads:
            logging.info('Downloading {} ({} MB)...'.format(file_.name, download.size_in_mb))

            file_destination = os.path.join(download_directory, download.name + '.zip')
            return await self.event_loop.run_in_executor(self.process_pool,
                                                         self._download_file_wget_process, download, file_destination)

    def _download_file_wget_process(self, download, file_destination):
        proc = subprocess.run(['wget', download.link, '-qO', file_destination, '--show-progress'])
        if proc.returncode == 0:
            self._unzip(file_destination)
            return True
        else:
            return False

    async def upload(self, torrent):
        #TODO: Test after API-Change
        src = None
        if type(torrent) is str:
            src = torrent
        elif str(torrent.__class__).rsplit('.', 1)[-1].startswith('PirateBayResult'):
            src = torrent.magnet

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
        if type(file_) is File:
            response_text = await self._make_request('/item/delete', data={'id': file_.id})
        else:
            response_text = await self._make_request('/folder/delete', data={'id': file_.id})
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = None
            return True
        logging.error('Could not delete file {}: {}'.format(file_, response_json.get('message')))
        return False

    async def get_file_from_transfer(self, transfer_):
        #TODO: Test after API-Change
        if not self.file_list_cached:
            await self.get_files()
        for file_ in self.file_list_cached:
            if file_.hash == transfer_.hash:
                return file_

        logging.error('No file for transfer "{}" found'.format(transfer_.name))

    async def get_file_download(self, file_):
        #TODO: Test after API-Change
        if type(file_) is File:
            return None # file_
        # TODO: how to generate a zip from folder
        # TODO: how to handle Torrents? Test with long-running torrent (low seeders)
        response_text = await self._make_request('/zip/generate', data={'items': {'folders': [file_.id]}})
        success, response_json = self._validate_to_json(response_text)
        print(response_json)
        if success:
            return File(response_json)

        logging.error('Could not download file "{}": {}'.format(file_.name, response_json.get('message', '?')))

    async def get_files(self):
        if self.file_list_cached is not None:
            return self.file_list_cached
        response_text = await self._make_request('/folder/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = []
            for properties_ in response_json.get('content', []):
                if not properties_:
                    continue
                if properties_.get('type', '') == 'file':
                    self.file_list_cached.append(File(properties_))
                if properties_.get('type', '') == 'folder':
                    self.file_list_cached.append(Folder(properties_))
            return self.file_list_cached
        logging.error('Error while getting files. Was: {}'.format(response_json.get('message')))
        return []

    async def get_transfers(self):
        #TODO: Test after API-Change
        response_text = await self._make_request('/transfer/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            return [Transfer(properties_) for properties_ in response_json.get('transfers', []) if properties_]
        logging.error('Error while getting transfers. Was: {}'.format(response_json.get('message')))
        return []

    async def _make_request(self, url, data=None):
        """ Do a request, take care of the login, timeouts and exceptions """
        data_ = self.login_data
        if data is not None:
            data_.update(data)
        if self.aiohttp_session is None:
            self.aiohttp_session = aiohttp.ClientSession(loop=self.event_loop)

        retries = 3
        for _ in range(retries):
            try:
                async with self.aiohttp_session.post(self.url + url, data=data_, timeout=10) as r_:
                    text = await r_.text()
                    if r_.status == 200:
                        return text
            except (asyncio.TimeoutError, aiohttp.ClientConnectionError):
                logging.warning('Timeout, retrying...')
                await asyncio.sleep(1)
            except Exception as e:
                logging.error('Caught Exception "{}" while making a get-request to "{}"'.format(e.__class__, url))
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
        if not auth:
            auth = os.path.join(os.path.dirname(__file__), 'auth.txt')

        if ':' in auth:
            username, password = auth.strip().split(':')
        elif os.path.exists(auth):
            with open(auth, 'r') as f:
                username, password = f.read().strip().split(':')
        else:
            with open(auth, 'w') as f:
                username = input('Please enter your premiumize.me-username: ')
                password = getpass.getpass(prompt='Please enter your premiumize.me-password: ')
                f.write(':'.join([username, password]))

        if not (username and password):
            logging.error('Authentication file not found or credentials were malformed!')
            return {}

        return {'customer_id': username, 'pin': password}

    def __bool__(self):
        return bool(self.login_data.get('customer_id') and self.login_data.get('pin'))
