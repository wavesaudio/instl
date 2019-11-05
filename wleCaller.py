from ctypes import *
from contextlib import contextmanager
import pathlib
import platform
import utils


class WLECaller(object):
    """ WLECaller: this class knows to search for the WavesLicenseEngine.bundle load it
        and call it's functions.
        WLECaller.devices(): returns a list of devices capable of carrying licenses
        WLECaller.files(): returns a list of license files on all devices
        WLECaller.licenses(): returns a list of licenses
    """
    def load_wle_dll(self):
        try:
            os_names = utils.get_current_os_names()

            if 'Mac' in os_names:
                wle_modules_folder = pathlib.Path("/Library/Application Support/Waves/Modules")
                wle_bundle_path = pathlib.Path(wle_modules_folder, "WavesLicenseEngineDebug.bundle")
                dll_name = "WavesLicenseEngine"
                wle_debug = wle_bundle_path.is_dir()
                if not wle_debug:
                    wle_bundle_path = pathlib.Path(wle_modules_folder, "WavesLicenseEngine.bundle")
                architecture_folder = "MacOS"
            elif 'Win' in os_names:
                wle_modules_folder = pathlib.Path("C:/ProgramData/Waves Audio/Modules")
                wle_bundle_path = pathlib.Path(wle_modules_folder, "WavesLicenseEngineDebug.bundle")
                wle_debug = wle_bundle_path.is_dir()
                if wle_debug:
                    dll_name = "WavesLicenseEngineDebug.dll"
                else:
                    wle_bundle_path = pathlib.Path(wle_modules_folder, "WavesLicenseEngine.bundle")
                    dll_name = "WavesLicenseEngine.dll"
                if platform.architecture()[0] == "32bit":
                    architecture_folder = "Win32"
                else:
                    architecture_folder = "Win64"
            wle_dll_path = pathlib.Path(wle_bundle_path, "Contents", architecture_folder, dll_name)
            self.lib_wle = LibraryLoader(CDLL).LoadLibrary(str(wle_dll_path))
            self.lib_wle.wls_entry.argtypes = [c_char_p, POINTER(c_char_p)]
            self.lib_wle.wls_free_ptr.argtypes = [c_char_p]
            #self.logger.info("loaded wle at %s", wle_dll_path)
        except Exception as ex:
            self.logger.error("failed to load wle at %s, %s", wle_dll_path, ex)

    def __init__(self, in_logger = None):
        self.logger = in_logger
        self.lib_wle = None
        self.load_wle_dll()

    @contextmanager
    def _call_wle(self, request):
        if self.lib_wle is None:  # in case wle failed to load when pivot was launched
            self.load_wle_dll()
        if self.lib_wle is not None:
            request_bytes = request.encode()
            answer = c_char_p()
            self.lib_wle.wls_entry(request_bytes, byref(answer))
            answer_str = answer.value.decode("utf-8")
            yield answer_str
            self.lib_wle.wls_free_ptr(answer)
        else:
            yield ""

    @contextmanager
    def _call_wle_split_and_filter(self, request):
        with self._call_wle(request) as answer_str:
            yield filter(bool, [ds.strip() for ds in answer_str.split("\n")])

    def devices(self):
        with self._call_wle_split_and_filter("{devices}") as wle_answers:
            yield from wle_answers

    def files(self):
        with self._call_wle_split_and_filter("{files: {format: text}}") as wle_answers:
            yield from wle_answers

    def licenses(self):
        with self._call_wle_split_and_filter("{licenses: {format: text}}") as wle_answers:
            yield from wle_answers

    def sync(self, force):
        with self._call_wle("{sync: {force_sync: %s}}" % force) as wle_result:
            return wle_result

    def version(self):
        with self._call_wle("version") as wle_result:
            return wle_result

    def server(self):
        with self._call_wle("server") as wle_result:
            return wle_result
