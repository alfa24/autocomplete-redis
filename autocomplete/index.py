import json

import redis

try:
    from django.conf import settings
except ImportError:
    settings = {}

PREFIX = settings.get('REDIS_AUTOCOMPLETE', {}).get('prefix', 'ra')
HOST = settings.get('REDIS_AUTOCOMPLETE', {}).get('host', 'localhost')
PORT = settings.get('REDIS_AUTOCOMPLETE', {}).get('port', 6379)
DB = settings.get('REDIS_AUTOCOMPLETE', {}).get('db', 0)
LIMITS = settings.get('REDIS_AUTOCOMPLETE', {}).get('limits', 5)


class Autocomplete(object):
    """Autocomplete"""

    def __init__(self, scope, prefix=PREFIX, host=HOST, port=PORT, db=DB, limits=LIMITS, cached=True):
        self.r = redis.Redis(host=host, port=port, db=db)
        self.scope = scope
        self.cached = cached
        self.limits = limits
        self.database = f'{prefix}:database:{scope}'
        self.indexbase = f'{prefix}:indexbase:{scope}'

    def _get_index_key(self, key):
        return f'{self.indexbase}:{key}'

    def del_index(self):
        prefixes = self.r.smembers(self.indexbase)
        for prefix in prefixes:
            self.r.delete(self._get_index_key(prefix))
        self.r.delete(self.indexbase)
        self.r.delete(self.database)

    @staticmethod
    def sanity_check(item):
        """Make sure item has key that's needed"""

        for key in ('uid', 'term'):
            if key not in item:
                raise Exception(f'Item should have key {key}')

    def add_item(self, item):
        """Create index for ITEM"""

        self.sanity_check(item)
        self.r.hset(self.database, item.get('uid'), json.dumps(item))
        for prefix in self.prefixes_for_term(item['term']):
            self.r.sadd(self.indexbase, prefix)
            self.r.zadd(self._get_index_key(prefix), {item.get('uid'): item.get('score', 0)})

    def del_item(self, item):
        """Delete ITEM from the index"""

        for prefix in self.prefixes_for_term(item['term']):
            self.r.zrem(self._get_index_key(prefix), item.get('uid'))
            if not self.r.zcard(self._get_index_key(prefix)):
                self.r.delete(self._get_index_key(prefix))
                self.r.srem(self.indexbase, prefix)

    def update_item(self, item):
        self.del_item(item)
        self.add_item(item)

    @staticmethod
    def prefixes_for_term(term):
        """Get prefixes for TERM"""

        # Normalization
        term = term.lower()

        # Prefixes for term
        prefixes = []
        tokens = term.split(' ')
        for token in tokens:
            word = token
            for i in range(1, len(word) + 1):
                prefixes.append(word[:i])

        return prefixes

    @staticmethod
    def normalize(prefix):
        """Normalize the search string"""

        tokens = prefix.lower().split(' ')
        return [token for token in tokens]

    def search_query(self, prefix):
        search_strings = self.normalize(prefix)

        if not search_strings:
            return []

        cache_key = self._get_index_key('|'.join(search_strings))

        if not self.cached or not self.r.exists(cache_key):
            self.r.zinterstore(cache_key, [self._get_index_key(x) for x in search_strings])
            self.r.expire(cache_key, 10 * 60)

        ids = self.r.zrevrange(cache_key, 0, self.limits)
        if not ids:
            return ids

        return self.r.hmget(self.database, *ids)
