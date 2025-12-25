import random
import string
import time
from contextlib import contextmanager

import redis


class RedisClient(redis.Redis):
    """ RedisClient: a wrapper around redis.StrictRedis that adds:
        - connects to port 63179 instead of 6379
        - sets decode_responses to be True so all replies from redis are translated from bytes to utf-8
        - lock/unlock functionality
        - delete keys by pattern
    """
    decode_responses=True
    random_str_choices = string.ascii_uppercase + string.ascii_lowercase + string.digits
    unlock_lua_code = """if redis.call('get', KEYS[1]) == KEYS[2]
                            then
                                return redis.call('del', KEYS[1])
                            else
                                return 0
                            end"""
    unlock_lua_script = None
    del_keys_by_pattern_lua_code = """  local key_list = redis.call('KEYS', KEYS[1])
                                        if #key_list == 0 then
                                            return 0
                                        else
                                            return redis.call('DEL', unpack(key_list))
                                        end"""
    del_keys_by_pattern_lua_script = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        super().__init__(port=self.port, host=self.host, decode_responses=self.decode_responses)
        if self.__class__.unlock_lua_script is None:
            self.__class__.unlock_lua_script = self.register_script(self.unlock_lua_code)
        if self.__class__.del_keys_by_pattern_lua_script is None:
            self.__class__.del_keys_by_pattern_lua_script = self.register_script(self.del_keys_by_pattern_lua_code)

    @classmethod
    def del_by_pattern(cls, redis_obj, keys_pattern):
        """ del_by_pattern deletes keys according to a pattern such as wv:wle:device:*
            del_by_pattern is implemented with a lua script that is passed to the server
            when RedisClient is initialized.
            del_by_pattern is implemented as a class method so it can be used by both
            RedisClient or a pipeline object.
            Usage: redisClient.RedisClient.del_by_pattern(redis_instance, "100*")
        """
        cls.del_keys_by_pattern_lua_script(keys=(keys_pattern,), client=redis_obj)

    @contextmanager
    def transaction_pipeline(self):
        pl = self.pipeline()
        yield pl
        pl.execute()

    @contextmanager
    def lock_redis(self, lock_name, expire_seconds=5, re_trys=1):
        """ lock redis raise exception if failed """
        lock_value = ''.join(random.choice(self.random_str_choices) for i in range(64))
        for re_try in range(re_trys):
            locked = self.set(lock_name, lock_value, nx=True)  # , ex=expire_seconds
            if locked:
                yield locked
                self.unlock_lua_script(keys=(lock_name, lock_value))
                break
            else:
                time.sleep(1)
        else:
            raise TimeoutError("Unable to lock redis, lock name="+lock_name)

    @contextmanager
    def try_lock_redis(self, lock_name, expire_seconds=5, re_trys=1):
        """ lock redis yield False if failed """
        try:
            with self.lock_redis(lock_name, expire_seconds=expire_seconds, re_trys=re_trys):
                yield True
        except TimeoutError:
            yield False

    def force_remove_lock(self, lock_name):
        retVal = self.delete(lock_name)
        print("force removed lock", lock_name, "retVal:", retVal)
        return retVal

    # this function is listed as part of the redis.StrictRedis API but is not implemented
    # so here is a copy
    def pubsub_channels(self, pattern='*'):
            """
            Return a list of channels that have at least one subscriber
            """
            return self.execute_command('PUBSUB CHANNELS', pattern)
