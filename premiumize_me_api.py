import os
import json
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

    async def download_file(self, item, download_directory):
        files = await self.get_files_to_download(item)
        if not files:
            return

        if len(files) > 1:
            download_directory = os.path.join(download_directory, item.name)
            if not os.path.exists(download_directory):
                os.mkdir(download_directory)

        return_codes = []
        for file in files:
            if self._file_exists(file, download_directory):
                continue

            async with self.max_simultaneous_downloads:
                logging.info('Downloading {} ({} MB)...'.format(file.name, file.size_in_mb))

                file_destination = os.path.join(download_directory, file.name)
                return_codes.append(await self.event_loop.run_in_executor(self.process_pool,
                                                             self._download_file_wget_process,
                                                             file, file_destination))
        return False not in return_codes

    def _download_file_wget_process(self, file, file_destination):
        proc = subprocess.run(['wget', file.link, '-qO', file_destination, '--show-progress'])
        if proc.returncode == 0:
            #self._unzip(file_destination)
            return True
        else:
            return False

    async def upload(self, torrent):
        src = None
        if type(torrent) is str:
            src = torrent
        elif str(torrent.__class__).rsplit('.', 1)[-1].startswith('PirateBayResult'):
            src = torrent.magnet

        response_text = await self._make_request("/transfer/create", data={'src': src})
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
        elif type(file_) is Folder:
            response_text = await self._make_request('/folder/delete', data={'id': file_.id})
        elif type(file_) is Transfer:
            response_text = await self._make_request('/transfer/delete', data={'id': file_.id})
        else:
            logging.error('Unknown type of file to delete: {}'.format(file_))
            return True
        success, response_json = self._validate_to_json(response_text)
        if success:
            self.file_list_cached = None
            return True
        logging.error('Could not delete file {}: {}'.format(file_, response_json.get('message')))
        return False

    async def get_file_from_transfer(self, transfer_):
        if not self.file_list_cached:
            await self.update_files()

        for file_ in self.file_list_cached:
            if (file_.type == 'folder' and file_.id == transfer_.folder_id) or \
               (file_.type == 'file' and file_.id == transfer_.file_id):
                return file_

        logging.error('No file for transfer "{}" found, status is: "{}"'.format(transfer_.name, transfer_.status_msg()))

    async def get_files_to_download(self, item):
        #TODO: Test after API-Change
        if type(item) is File:
            return [item]

        # Currently download every file separately, since zip-generation is broken (in my code) right now
        response_text = await self._make_request('/folder/list', data={'id': item.id})
        success, response_json = self._validate_to_json(response_text)
        if success:
            return [File(file_) for file_ in response_json.get('content', [])]

        # TODO: how to generate a zip from folder
        # TODO: how to handle Torrents? Test with long-running torrent (low seeders)
        # response_text = await self._make_request('/zip/generate', data={'items': {'folders': [file_.to_data()]}})
        # success, response_json = self._validate_to_json(response_text)
        # if success:
        #     return File(response_json)

        logging.error('Could not download "{}": {}'.format(file_.name, response_json.get('message', '?')))

    async def update_files(self):
        if self.file_list_cached:
            return

        file_list_cached_ = []
        response_text = await self._make_request('/folder/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            for properties_ in response_json.get('content', []):
                if not properties_:
                    continue
                if properties_.get('type', '') == 'file':
                    file_list_cached_.append(File(properties_))
                if properties_.get('type', '') == 'folder':
                    file_list_cached_.append(Folder(properties_))
        else:
            logging.error('Error while updating files. Was: {}'.format(response_json.get('message')))

        self.file_list_cached = file_list_cached_

    async def get_files(self, recursion_max=5):
        if self.file_list_cached:
            return self.file_list_cached
        else:
            await self.update_files()
            if recursion_max > 0:
                return await self.get_files(recursion_max=recursion_max-1)

        return []

    async def get_transfers(self):
        response_text = await self._make_request('/transfer/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            transfers = []
            for properties_ in response_json.get('transfers', []):
                transfer_ = Transfer(properties_)
                if not self._validate_transfer(transfer_):
                    await self.delete(transfer_)
                else:
                    transfers.append(transfer_)
            return transfers
        logging.error('Error while getting transfers. Was: {}'.format(response_json.get('message')))
        return []

    @staticmethod
    def _validate_transfer(transfer):
        if not (transfer.folder_id or transfer.file_id) and transfer.status in ['finished', 'error']:
            return False
        return True

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
            # TODO: what if file is not zipped?
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
