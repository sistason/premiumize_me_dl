# premiumize.me.dl
Download/Upload your premiumize.me torrents via cli

## Usage
Download files from your Premiumize.me account
python3 premiumize_me_download.py file [file, ...] /your/download/path [-a auth] [-d days] [-c]
 - file: Regular expressions for which files to get
 - -a: Supply authentication information. These can be either:
   - A string in the format "user:pass"
   - A txt containing "user:pass"
   - optional, looks for a auth.txt in the file-directory, otherwise asks.
 - -d, --delete: Delete downloaded $files, if they are older than $day days.
 - -c, --cleanup: Ignore $files, just delete all files older than $days.

Upload links for Premiumize.me to download
python3 premiumize_me_upload.py link [link, ...] [-a auth]
 - link: Anything the premiumize.me downloader likes (pirate-bay-url, magnet, ...)
 - -a: Supply authentication information. These can be either:
   - A string in the format "user:pass"
   - A file containing "user:pass"
   - optional, looks for the auth-file in the file-directory otherwise or asks.

## Dependencies
 - python 3.5+ (asyncio)
 - python3-aiofiles
 - python3-aiohttp
 - A valid premiumize.me account with Premium ;)
