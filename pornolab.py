# -*- coding: utf-8 -*-

#VERSION: 1.0
#AUTHORS: TainakaDrums [tainakadrums@yandex.ru]
"""Pornolab search engine plugin for qBittorrent."""

# Replace YOUR_USERNAME_HERE and YOUR_PASSWORD_HERE with your Pornolab username and password
credentials = {
    'login_username': '',
    'login_password': '',
}

# Logging
import logging
logger = logging.getLogger()
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.WARNING)

# Try blocks are used to circumvent Python2/3 modules discrepancies and use a single script for both versions.
try:
    import cookielib
except ImportError:
    import http.cookiejar as cookielib

try:
    from urllib import urlencode, quote, unquote
    from urllib2 import build_opener, HTTPCookieProcessor, URLError, HTTPError
except ImportError:
    from urllib.parse import urlencode, quote, unquote
    from urllib.request import build_opener, HTTPCookieProcessor
    from urllib.error import URLError, HTTPError

try:
    from HTMLParser import HTMLParser
except ImportError:
    from html.parser import HTMLParser

import tempfile
import os
import re

from novaprinter import prettyPrinter

def dict_encode(dict, encoding='cp1251'):
    """Encode dict values to encoding (default: cp1251)."""
    encoded_dict = {}
    for key in dict:
        encoded_dict[key] = dict[key].encode(encoding)
    return encoded_dict

class pornolab(object):
    """Pornolab search engine plugin for qBittorrent."""
    name = 'Pornolab'
    url = 'https://pornolab.net' # We MUST produce an URL attribute at instantiation time, otherwise qBittorrent will fail to register the engine, see #15

    @property
    def forum_url(self):
        return self.url + '/forum'

    @property
    def login_url(self):
        return self.forum_url + '/login.php'

    @property
    def download_url(self):
        return self.forum_url + '/dl.php'

    @property
    def search_url(self):
        return self.forum_url + '/tracker.php'

    def __init__(self):
        """Initialize Pornolab search engine, signing in using given credentials."""
        # Initialize various objects.
        self.cj = cookielib.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cj))
        self.url = 'https://pornolab.net'  # Override url with the actual URL to be used (in case official URL isn't accessible)
        self.credentials = credentials
        # Add submit button additional POST param.
        self.credentials['login'] = u'Вход'
        try:
            logging.info("Trying to connect using given credentials.")
            response = self.opener.open(self.login_url, urlencode(dict_encode(self.credentials)).encode())
            # Check if response status is OK.
            if response.getcode() != 200:
                raise HTTPError(response.geturl(), response.getcode(), "HTTP request to {} failed with status: {}".format(self.login_url, response.getcode()), response.info(), None)
            # Check if login was successful using cookies.
            if not 'bb_data' in [cookie.name for cookie in self.cj]:
                logging.debug(self.cj)
                raise ValueError("Unable to connect using given credentials.")
            else:
                logging.info("Login successful.")
        except (URLError, HTTPError, ValueError) as e:
            logging.error(e)

    def download_torrent(self, url):
        """Download file at url and write it to a file, print the path to the file and the url."""
        # Make temp file.
        file, path = tempfile.mkstemp('.torrent')
        file = os.fdopen(file, "wb")
        # Set up fake POST params, needed to trick the server into sending the file.
        id = re.search(r'dl\.php\?t=(\d+)', url).group(1)
        post_params = {'t': id,}
        # Download torrent file at url.
        try:
            response = self.opener.open(url, urlencode(dict_encode(post_params)).encode())
            # Only continue if response status is OK.
            if response.getcode() != 200:
                raise HTTPError(response.geturl(), response.getcode(), "HTTP request to {} failed with status: {}".format(url, response.getcode()), response.info(), None)
        except (URLError, HTTPError) as e:
            logging.error(e)
            raise e
        # Write it to a file.
        data = response.read()
        file.write(data)
        file.close()
        # Print file path and url.
        print(path+" "+url)

    class Parser(HTMLParser):
        """Implement a simple HTML parser to parse results pages."""

        def __init__(self, engine):
            """Initialize the parser with url and tell him if he's on the first page of results or not."""

            HTMLParser.__init__(self, convert_charrefs=True)

            self.engine = engine
            self.results = []
            self.other_pages = []
            self.cat_re = re.compile(r'tracker\.php\?f=\d+')
            self.pages_re = re.compile(r'tracker\.php\?.*?start=(\d+)')
            self.reset_current()

        def reset_current(self):
            """Reset current_item (i.e. torrent) to default values."""
            self.current_item = {'cat': None,
                                 'name': None,
                                 'link': None,
                                 'size': None,
                                 'seeds': None,
                                 'leech': None,
                                 'desc_link': None,}

        def handle_data(self, data):
            """Retrieve inner text information based on rules defined in do_tag()."""
            for key in self.current_item:
                if self.current_item[key] == True:
                    if key == 'size':
                        self.current_item['size'] = data.replace('\xa0', '')
                    else:
                        self.current_item[key] = data

        def handle_starttag(self, tag, attrs):
            """Pass along tag and attributes to dedicated handlers. Discard any tag without handler."""
            try:
                getattr(self, 'do_{}'.format(tag))(attrs)
            except:
                pass

        def handle_endtag(self, tag):
            """Add last item manually on html end tag."""
            # We add last item found manually because items are added on new
            # <tr class="tCenter"> and not on </tr> (can't do it without the attribute).
            if tag == 'html' and self.current_item['seeds']:
                self.results.append(self.current_item)

        def do_tr(self, attr):
            """<tr class="tCenter"> is the big container for one torrent, so we store current_item and reset it."""
            params = dict(attr)
            if 'tCenter' in params.get('class', ''):

                if self.current_item['seeds']:
                    self.results.append(self.current_item)
                    self.reset_current()

        def do_a(self, attr):
            """<a> tags can specify torrent link in "href" or category or name or size in inner text. Also used to retrieve further results pages."""
            params = dict(attr)
            try:
                if self.cat_re.search(params['href']):
                    self.current_item['cat'] = True
                elif 'tLink' in params['class'] and not self.current_item['desc_link']:
                    self.current_item['desc_link'] = self.engine.forum_url + params['href'][1:]
                    self.current_item['link'] = self.engine.download_url + params['href'].split('viewtopic.php')[-1]
                    self.current_item['name'] = True
                elif self.current_item['size'] == None and 'dl-stub' in params['class']:
                    self.current_item['size'] = True
                # If we're on the first page of results, we search for other pages.
                elif self.first_page:
                    pages = self.pages_re.search(params['href'])
                    if pages:
                        if pages.group(1) not in self.other_pages:
                            self.other_pages.append(pages.group(1))
            except KeyError:
                pass

        def do_td(self, attr):
            """<td> tags give us number of leechers in inner text and can signal torrent size in next <a> tag."""
            params = dict(attr)
            try:
                if 'leechmed' in params['class']:
                    self.current_item['leech'] = True
            except KeyError:
                pass

        def do_b(self, attr):
            """<b class="seedmed"> give us number of seeders in inner text."""
            params = dict(attr)
            if 'seedmed' in params.get('class', ''):
                self.current_item['seeds'] = True

        def search(self, what, start=0):
            """Search for what starting on specified page. Defaults to first page of results."""
            logging.debug("parse_search({}, {})".format(what, start))

            # If we're on first page of results, we'll try to find other pages
            if start == 0:
                self.first_page = True
            else:
                self.first_page = False

            try:
                response = self.engine.opener.open('{}?nm={}&start={}'.format(self.engine.search_url, quote(what), start))
                # Only continue if response status is OK.
                if response.getcode() != 200:
                    raise HTTPError(response.geturl(), response.getcode(), "HTTP request to {} failed with status: {}".format(self.engine.search_url, response.getcode()), response.info(), None)
            except (URLError, HTTPError) as e:
                logging.error(e)
                raise e

            # Decode data and feed it to parser
            data = response.read().decode('cp1251')
            data = re.sub(r'<wbr>|<b>|<\/b>', '', data)
            self.feed(data)

    def search(self, what, cat='all'):
        """Search for what on the search engine."""
        # Instantiate parser
        self.parser = self.Parser(self)

        # Decode search string
        what = unquote(what)
        logging.info("Searching for {}...".format(what))

        # Search on first page.
        logging.info("Parsing page 1.")
        self.parser.search(what)

        # If multiple pages of results have been found, repeat search for each page.
        logging.info("{} pages of results found.".format(len(self.parser.other_pages)+1))
        for start in self.parser.other_pages:
            logging.info("Parsing page {}.".format(int(start)//50+1))
            self.parser.search(what, start)

        # PrettyPrint each torrent found, ordered by most seeds
        self.parser.results.sort(key=lambda torrent:torrent['seeds'], reverse=True)
        for torrent in self.parser.results:

            torrent['engine_url'] = 'https://pornolab.net' # Kludge, see #15
            if __name__ != "__main__": # This is just to avoid printing when I debug.
                prettyPrinter(torrent)
            else:
                print(torrent)


        self.parser.close()
        logging.info("{} torrents found.".format(len(self.parser.results)))

# For testing purposes.
if __name__ == "__main__":
    engine = pornolab()
    # engine.search('2020')
