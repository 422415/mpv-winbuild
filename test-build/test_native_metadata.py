"""Exercise producer rejection paths without requiring a compiler or real binaries."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("producer", Path(__file__).with_name("produce-native-metadata.py"))
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


class NativeMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.ass, self.build, self.binaries = [self.root / n for n in ("source", "ass", "build", "binaries")]
        for directory in (self.source / "etc", self.source / "video/filter", self.ass, self.build / "meson-info", self.binaries):
            directory.mkdir(parents=True)
        self.contract = dict(schemaVersion=1, privateSampleAbi=1, privatePlayerSampleAbi=1,
            privateOutputAbi=1, nullHardwareFramesOptIn=1, requiredFeatures=["D3D11", "ASS_BLUR_DEFERRED"],
            requiredOptions=dict(cplayer=True, libmpv=True))
        self.save_contract()
        (self.source / "video/filter/ajn_sample_shared.h").write_text("#define AJN_SAMPLE_VERSION 1\n")
        (self.build / "config.h").write_text("#define HAVE_D3D11 1\n#define HAVE_ASS_BLUR_DEFERRED 1\n")
        (self.build / "meson-info/intro-projectinfo.json").write_text(json.dumps(dict(descriptive_name="mpv")))
        self.options = [dict(name="cplayer", value=True), dict(name="libmpv", value=True)]
        self.save_options()
        self.imports = {"libmpv-2.dll": ["api-ms-win-crt-runtime-l1-1-0.dll"], "mpv.exe": ["ucrtbase.dll"]}
        for name in self.imports:
            (self.binaries / name).write_bytes(name.encode())
        self.output = self.root / "evidence.json"
        self.exports = []
        def run(*args):
            if args[0] == "objdump":
                return "file format pei-x86-64\n" + "\n".join("DLL Name: " + name for name in self.imports[Path(args[-1]).name]) + "\n" + "\n".join("[ 1] " + name for name in self.exports)
            if "rev-parse" in args:
                return "a" * 40 if args[2] == str(self.source) else "b" * 40
            if "status" in args:
                return ""
            raise AssertionError(args)
        self.addCleanup(patch.stopall)
        patch.object(producer, "run", side_effect=run).start()
        patch.dict(os.environ, {"GITHUB_REPOSITORY": "fixture/build", "GITHUB_SHA": "c" * 40,
            "GITHUB_RUN_ID": "fixture", "AJN_MPV_SHA": "a" * 40, "AJN_LIBASS_SHA": "b" * 40}).start()

    def save_contract(self):
        (self.source / "etc/ajn-native-capabilities.json").write_text(json.dumps(self.contract))

    def save_options(self):
        (self.build / "meson-info/intro-buildoptions.json").write_text(json.dumps(self.options))

    def produce(self, linkage="static"):
        producer.produce(self.source, self.ass, self.build, [self.binaries], self.output, linkage)
        return json.loads(self.output.read_text())

    def test_static_checks_actual_options_not_invented_config_features(self):
        record = self.produce()
        self.assertEqual(record["buildOptions"], {"cplayer": True, "libmpv": True})
        self.assertEqual(record["sources"]["mpv"], "a" * 40)

    def test_required_option_disabled(self):
        self.options[1]["value"] = False
        self.save_options()
        with self.assertRaisesRegex(ValueError, "build option"): self.produce()
        self.assertFalse(self.output.exists())

    def test_required_feature_missing(self):
        (self.build / "config.h").write_text("#define HAVE_D3D11 1\n")
        with self.assertRaisesRegex(ValueError, "Missing native features"): self.produce()

    def test_wrong_sample_abi(self):
        (self.source / "video/filter/ajn_sample_shared.h").write_text("#define AJN_SAMPLE_VERSION 2\n")
        with self.assertRaisesRegex(ValueError, "Sample source ABI"): self.produce()

    def test_consumer_must_use_ucrt(self):
        self.imports["libmpv-2.dll"] = ["msvcrt.dll"]
        with self.assertRaisesRegex(ValueError, "UCRT import"): self.produce()
        self.imports["libmpv-2.dll"].append("ucrtbase.dll")
        with self.assertRaisesRegex(ValueError, "Mixed CRT"): self.produce()

    def test_linkage_disagreement(self):
        self.imports["libmpv-2.dll"].append("avformat-63.dll")
        with self.assertRaisesRegex(ValueError, "linkage differs"): self.produce()

    def test_complete_shared_dependency_set(self):
        self.imports["libmpv-2.dll"].append("avformat-63.dll")
        for name in ["avformat-63.dll", "libstdc++-6.dll", *[f"dependency-{i}.dll" for i in range(135)]]:
            (self.binaries / name).write_bytes(name.encode())
            self.imports[name] = ["ucrtbase.dll"]
        self.assertEqual(len(self.produce("shared")["files"]), 139)

    def test_source_pin_mismatch(self):
        os.environ["AJN_MPV_SHA"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "wrong source revision"): self.produce()

    def enable_probe(self):
        self.contract["privateProbeAbi"] = 1
        self.save_contract()
        (self.source / "common").mkdir()
        (self.source / "common/ajn_probe.h").write_text("#define AJN_PROBE_VERSION 1\n")

    def test_probe_requires_both_actual_exports(self):
        self.enable_probe()
        with self.assertRaisesRegex(ValueError, "Missing native probe export"): self.produce()
        self.exports.append("mpv_ajn_probe_v1")
        with self.assertRaisesRegex(ValueError, "mpv_ajn_probe_free_v1"): self.produce()
        self.exports.append("mpv_ajn_probe_free_v1")
        self.assertEqual(self.produce()["privateProbeAbi"], 1)

    def test_probe_rejects_wrong_source_abi(self):
        self.enable_probe()
        (self.source / "common/ajn_probe.h").write_text("#define AJN_PROBE_VERSION 2\n")
        with self.assertRaisesRegex(ValueError, "probe source contract"): self.produce()


if __name__ == "__main__": unittest.main()
