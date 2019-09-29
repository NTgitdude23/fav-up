import requests
import base64
import argparse

import tqdm
import mmh3
from ipwhois import IPWhois
from bs4 import BeautifulSoup
from shodan import Shodan
from shodan.cli.helpers import get_api_key

class FavUp(object):
    def __init__(self, *args, **kwargs):
        """ Parse the arguments
        """
        self.show = None
        self._iterator = None

        self.key = None
        self.keyFile = None
        self.shodanCLI = None
        self.faviconFile = None
        self.faviconURL = None
        self.web = None
        self.favhash = None
        self.shodan = None
        self.maskIP = None
        self.maskISP = None
        self.realIPs = []
        self.fileList = []
        self.urlList = []
        self.webList = []
        self.faviconsList = []

        if kwargs.get('show'):
            self.show = True
            ap = argparse.ArgumentParser(prog="favup", usage="python3 %(prog)s [options]")

            ap.add_argument('-kf', '--key-file', help="Specify the file which contains the API key.")
            ap.add_argument('-k', '--key', help="Specify the API key.")
            ap.add_argument('-sc', '--shodan-cli', help="Load the API key from Shodan CLI.", action="store_true")

            ap.add_argument('-ff', '--favicon-file', help="Load the favicon icon from a local file.")
            ap.add_argument('-fu', '--favicon-url', help="Load the favicon icon from an URL.")
            ap.add_argument('-w', '--web', help="Extracts the favicon location from the page.")

            ap.add_argument('-fl', '--favicon-list',
                help="Iterate over a file that contains the full path of all the icons which you want to lookup.")
            ap.add_argument('-ul', '--url-list',
                help="Iterate over a file that contains the full URL of all the icons which you want to lookup.")
            ap.add_argument('-wl', '--web-list',
                help="Iterate over a file that contains all the domains which you want to lookup.")


            args = self._argsCheck(ap.parse_args())
            self.key = args.key
            self.keyFile = args.key_file
            self.shodanCLI = args.shodan_cli
            self.faviconFile = args.favicon_file
            self.faviconURL = args.favicon_url
            self.web = args.web
            self.fileList = _serializeListFile(args.favicon_list)
            self.urlList = _serializeListFile(args.url_list)
            self.webList = _serializeListFile(args.web_list)

            self.run()
    
    def _argsCheck(self, args):
        if not (args.key_file or args.key or args.shodan_cli):
            print('[x] Please specify the key with --key, --key-file or --shodan-cli.')
            exit(1)
        
        if not (args.favicon_file or args.favicon_url or args.web or
                args.favicon_list or args.url_list or args.web_list):
            print('[x] Please specify the source of the favicon with --favicon-file, --favicon-url, --web'+
                ', --favicon-list, --url-list or --web-list.')
            exit(1)

        return args
    
    def _serializeListFile(self, inputFile):
        """ Remove whitespace chars and lines
        """
        _output = []
        with open(inputFile, 'r') as inFile:
            for _l in inFile:
                if _l.strip():
                    _output.append(_l.strip())
        return _output


    def _runShodanSearch(self):
        if self.show:
            print(f"Favicon Hash: {self.favhash}")
        self.shodanSearch(self.favhash)

    def run(self):
        if self.keyFile:
            self.shodan = Shodan(open(self.keyFile, "r").readline().strip())
        elif self.key:
            self.shodan = Shodan(self.key)
        elif self.shodanCLI:
            self.shodan = Shodan(get_api_key())
        else:
            print('[x] Wrong input API key type.')
            exit(1)

        if self.faviconFile or self.fileList:
            self.fileList.append(self.faviconFile)
            for fav in self.fileList:
                data = open(fav, 'rb').read()
                self.favhash = self.faviconHash(data)
                self._runShodanSearch()
                self.faviconsList.append({
                    'favhash': self.favhash,
                    'file': fav,
                    'realIPs': self.realIPs
                    })
        if self.faviconURL or self.urlList:
            self.urlList.append(self.faviconURL)
            for fav in self.urlList:
                data = requests.get(fav, stream=True)
                self.deepConnectionLens(data)
                data = data.content
                self.favhash = self.faviconHash(data)
                self._runShodanSearch()
                self.faviconsList.append({
                    'favhash': self.favhash,
                    'url': self.faviconURL,
                    'maskIP': self.maskIP,
                    'maskISP': self.maskISP,
                    'realIPs': self.realIPs
                    })
        if self.web or self.webList:
            self.webList.append(self.web)
            for w in self.webList:
                try:
                    data = requests.get(f"https://{w}", stream=True)
                    self.deepConnectionLens(data)
                    data = self.searchFaviconHTML(w).content
                    self.favhash = self.faviconHash(data, web_source=True)
                    self._runShodanSearch()
                    self.faviconsList.append({
                        'favhash': self.favhash,
                        'url': data,
                        'maskIP': self.maskIP,
                        'maskISP': self.maskISP,
                        'realIPs': self.realIPs
                        })
                except requests.exceptions.ConnectionError:
                    print(f"[x] Connection refused by {w}.")
            if len(self.webList) == 1:
                exit(1)

    
    def faviconHash(self, data, web_source=None):
        if web_source:
            b64data = base64.encodebytes(data).decode()
        else:
            b64data = base64.encodebytes(data)
        return mmh3.hash(b64data)

    def searchFaviconHTML(self, link):
        data = requests.get(link, stream=True)
        soup = BeautifulSoup(data.content, 'html.parser')
        iconLink = soup.find('link', rel='icon').get("href")
        if not iconLink.startswith("http"):
            iconLink = link + "/" + iconLink
        return requests.get(iconLink)

    def shodanSearch(self, favhash):
        results = self.shodan.search(f"http.favicon.hash:{favhash}")
        for s in results["matches"]:
            self.realIPs.append(s['ip_str'])
            if self.show:
                print(f"Real-IP: {s['ip_str']}")

    def deepConnectionLens(self, response):
        try:
            mIP = list(response.raw._connection.sock.getpeername())[0]
        except AttributeError:
            mIP = list(response.raw._connection.sock.socket.getpeername())[0]

        self.maskIP = mIP
        self.maskISP = IPWhois(mIP).lookup_whois()['nets'][0]['name']
        if self.show:
            print(f"Mask-IP: {self.maskIP}")
            print(f"Mask-ISP: {self.maskISP}")

if __name__ == '__main__':
    FavUpApp = FavUp(show=True)
