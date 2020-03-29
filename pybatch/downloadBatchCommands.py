from configVar import config_vars
from http.cookies import SimpleCookie
import requests


class DownloadBatchCommands():

    @staticmethod
    def re_download_bad_files(bad_files_to_download,map_table):
        cookie_str = config_vars["COOKIE_JAR"].values[0]
        cookies = DownloadBatchCommands.get_cookie_dict_from_str(cookie_str)
        # open session
        dl_session = requests.Session()
        for bad_file in bad_files_to_download:
            download_url = map_table.get_sync_url_for_file_item(bad_file)
            DownloadBatchCommands.download_file(download_url, cookies, bad_file.download_path, dl_session)
        dl_session.close()

    @staticmethod
    def download_file(download_url, cookie, download_path, session):
        try:
            read = session.get(download_url, cookies=cookie)
            fo = open(download_path, 'wb')
            fo.write(read.content)
            fo.close()
            print(download_path + ' downloaded successfully!!!')
        # TODO: handle errors
        except requests.RequestException as e:
            print("Error :%s" % e)

    @staticmethod
    def get_cookie_dict_from_str(cookie_str):
        cookie = SimpleCookie()
        cookie.load(cookie_str)
        cookies = {}
        for key, morsel in cookie.items():
            if ":" in key:
                key = key.split(":")[1]
            cookies[key] = morsel.value
        return cookies