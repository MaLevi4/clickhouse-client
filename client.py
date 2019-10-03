from sys import version_info
if version_info < (3, 0):
    from urlparse import urlparse, parse_qs
else:
    from urllib.parse import urlparse, parse_qs

from logging import getLogger
logging = getLogger('clickhouse.client')

def raise_exception(data):
    import re
    from errors import Error
    errre = re.compile('Code: (\d+), e.displayText\(\) = DB::Exception: (.+?), e.what\(\) = (.+)')
    m = errre.search(data)
    if m:
        raise Error(*m.groups())
    else:
        raise Exception('unexpected answer: {}'.format(data))


class ClickHouseClient:

    def __init__(self, url=None, on_progress=None, **options):
        url = urlparse(url)
        self.scheme = url.scheme
        self.netloc = url.netloc
        self.options = dict([(key,str(val[0])) for key, val in parse_qs(url.query).items()])
        self.options.update(options)
        self.on_progress = on_progress


    def __repr__(self):
        return str( (self.scheme, self.netloc, self.options, self.on_progress) )


    def _on_header_x_clickhouse_progress(self, on_progress, key, val):
        from json import loads
        obj = loads(val)
        total = int(obj['total_rows'])
        read = int(obj['read_rows'])
        progress = float(read)/float(total)
        on_progress(total=total, read=read, progress=progress)


    def _on_header(self, on_progress):
        def wrapper(header):
            try:
                key, value = header.split(':', 1)
                value = value.strip()
                logging.debug('header={header} value={value}'.format(header=key, value=value))
                if key == 'X-ClickHouse-Progress':
                    self._on_header_x_clickhouse_progress(on_progress, key, value)
            except Exception as e:
                return
        return wrapper


    def _fetch(self, url, query, on_progress=None):
        logging.debug('query={query}'.format(query=query))
        from pycurl import Curl, POST, POSTFIELDS
        from io import BytesIO
        c = Curl()
        c.setopt(c.URL, url)
        c.setopt(POST, 1)
        c.setopt(POSTFIELDS, query)
        if on_progress:
            c.setopt(c.HEADERFUNCTION, self._on_header(on_progress))
        buffer = BytesIO()
        c.setopt(c.WRITEDATA, buffer)
        c.perform()
        c.close()
        return buffer.getvalue().decode('UTF-8')


    def _build_url(self, opts):
        from copy import deepcopy
        options = deepcopy(self.options)    #get copy of self.options
        options.update(opts)                #and override with opts
        options = dict([(key,val) for key, val in options.items() if val is not None]) #remove keys with None values
        urlquery = '&'.join(['{}={}'.format(key,val) for key,val in options.items()])
        url = '{self.scheme}://{self.netloc}/?{urlquery}'.format(self=self,urlquery=urlquery)
        logging.debug('url={url}'.format(url=url))
        return url


    def select(self, query, on_progress=None, **opts):
        import re
        from json import loads
        from result import Result
        if re.search('[)\s]FORMAT\s', query, re.IGNORECASE):
            raise Exception('Formatting is not available')
        query += ' FORMAT JSONCompact'
        url = self._build_url(opts)
        data = self._fetch(url, query, on_progress or self.on_progress)
        try:
            return Result(**loads(data))
        except BaseException:
            raise_exception(data)


    def execute(self, query, **kwargs):
        url = self._build_url(kwargs)
        data = self._fetch(url, query, on_progress=None)
        if data != '':
            raise_exception(data)
        return data

