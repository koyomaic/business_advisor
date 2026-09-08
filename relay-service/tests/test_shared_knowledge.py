from __future__ import annotations

import json
import os
import time

from app.shared_knowledge import (load_shared_mcp, mcp_entry_from_file,
                                 prepare_run, shared_memory_text, slug_valid,
                                 strip_jsonc)


class _Cfg:
    def __init__(self, shared_dir: str, xdg: str = "", exclude: list | None = None):
        self.shared_dir = shared_dir
        self.xdg_config_home = xdg
        self.relay_exclude_providers = exclude or []


def test_strip_jsonc_keeps_urls_and_drops_comments():
    txt = ('{\n "baseURL": "http://x:30131/v1", // trailing comment\n'
           ' "a": 1, /* block */ "b": [1, 2,],\n}')
    d = json.loads(strip_jsonc(txt))
    assert d["baseURL"] == "http://x:30131/v1"
    assert d["a"] == 1
    assert d["b"] == [1, 2]


def test_strip_jsonc_escapes():
    txt = r'{"s": "a \"q\" and // not comment", "n": 1,}'
    d = json.loads(strip_jsonc(txt))
    assert d["s"] == 'a "q" and // not comment' and d["n"] == 1


def test_slug_valid():
    assert slug_valid("my-skill_2.X")
    assert not slug_valid("")
    assert not slug_valid("../x")
    assert not slug_valid("a b")
    assert not slug_valid("a" * 60)


def test_mcp_entry_forms():
    assert mcp_entry_from_file("a", {"a": {"type": "local"}}) == {"type": "local"}
    assert mcp_entry_from_file("b", {"type": "remote", "url": "u"}) == {"type": "remote", "url": "u"}
    assert mcp_entry_from_file("c", {"x": {"y": 1}}) == {"y": 1}
    assert mcp_entry_from_file("d", "not-a-dict") == {}


def test_load_shared_mcp(tmp_path):
    (tmp_path / "mcp").mkdir()
    (tmp_path / "mcp" / "alpha.json").write_text(
        json.dumps({"type": "local", "command": ["python3", "a.py"], "enabled": True}))
    (tmp_path / "mcp" / "beta.json").write_text(
        json.dumps({"beta": {"type": "remote", "url": "http://b"}}))
    (tmp_path / "mcp" / "bad.json").write_text("not json")
    (tmp_path / "mcp" / "ignore.txt").write_text("x")
    m = load_shared_mcp(str(tmp_path))
    assert m["alpha"]["command"] == ["python3", "a.py"]
    assert m["beta"]["url"] == "http://b"
    assert "bad" not in m and "ignore" not in m


def test_load_shared_mcp_missing_dir(tmp_path):
    assert load_shared_mcp(str(tmp_path)) == {}


def test_shared_memory_text_empty(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "empty.md").write_text("   ")
    assert shared_memory_text(str(tmp_path)) is None


def test_prepare_run_injects_shared(tmp_path):
    sh = tmp_path / "shared"
    (sh / "skills" / "myskill").mkdir(parents=True)
    (sh / "skills" / "myskill" / "SKILL.md").write_text(
        "---\nname: myskill\ndescription: test skill\n---\nbody\n")
    (sh / "mcp").mkdir()
    (sh / "mcp" / "ping.json").write_text(
        json.dumps({"type": "local", "command": ["python3", "s.py"], "enabled": True}))
    (sh / "memory").mkdir()
    (sh / "memory" / "note.md").write_text("RULE-MARKER-42")
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)

    xdg = prepare_run(str(workdir), _Cfg(str(sh)))
    cfg_path = os.path.join(xdg, "opencode", "opencode.json")
    assert os.path.isfile(cfg_path)
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    assert str(sh / "skills") in cfg["skills"]["paths"]
    assert cfg["mcp"]["ping"]["command"] == ["python3", "s.py"]

    agents = (workdir / "AGENTS.md").read_text(encoding="utf-8")
    assert "RULE-MARKER-42" in agents
    assert (workdir / "home" / ".config" / "opencode" / "AGENTS.md").is_file()

    # 幂等：重复调用不报错，内容一致
    xdg2 = prepare_run(str(workdir), _Cfg(str(sh)))
    assert xdg2 == xdg
    assert json.load(open(cfg_path, encoding="utf-8"))["mcp"]["ping"]["command"] == ["python3", "s.py"]


def test_prepare_run_no_memory_no_agents_md(tmp_path):
    sh = tmp_path / "shared"
    (sh / "skills").mkdir(parents=True)
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)
    prepare_run(str(workdir), _Cfg(str(sh)))
    assert not (workdir / "AGENTS.md").exists()


def test_dws_seed_synced_into_home(tmp_path):
    sh = tmp_path / "shared"
    seed = sh / "secrets" / "dws-cli-seed" / "dws-cli"
    seed.mkdir(parents=True)
    (seed / "dek").write_text("seed-dek")
    (seed / "auth-token.enc").write_text("seed-token")
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)
    prepare_run(str(workdir), _Cfg(str(sh)))
    dst = workdir / "home" / ".local" / "share" / "dws-cli"
    assert (dst / "dek").read_text() == "seed-dek"
    assert (dst / "auth-token.enc").read_text() == "seed-token"
    assert (dst / "dek").stat().st_mode & 0o777 == 0o600


def test_dws_seed_newer_local_not_overwritten(tmp_path):
    sh = tmp_path / "shared"
    seed = sh / "secrets" / "dws-cli-seed" / "dws-cli"
    seed.mkdir(parents=True)
    (seed / "dek").write_text("old-seed")
    workdir = tmp_path / "wd"
    local = workdir / "home" / ".local" / "share" / "dws-cli"
    local.mkdir(parents=True)
    (local / "dek").write_text("fresh-from-task")
    os.utime(local / "dek", (time.time() + 60, time.time() + 60))
    prepare_run(str(workdir), _Cfg(str(sh)))
    assert (local / "dek").read_text() == "fresh-from-task"


def test_dws_seed_missing_noop(tmp_path):
    sh = tmp_path / "shared"
    sh.mkdir(parents=True)
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)
    prepare_run(str(workdir), _Cfg(str(sh)))
    assert not (workdir / "home" / ".local").exists()


def _base_xdg_with_providers(tmp_path):
    base = tmp_path / "basecfg" / "opencode"
    base.mkdir(parents=True)
    (base / "opencode.json").write_text(json.dumps({
        "provider": {
            "prod": {"npm": "x", "models": {"old": {}}},
            "local-only": {"npm": "x", "models": {"new": {}}},
        },
        "model": "prod/old",
    }))
    return str(tmp_path / "basecfg")


def test_prepare_run_excludes_local_only_provider(tmp_path):
    sh = tmp_path / "shared"
    (sh / "skills").mkdir(parents=True)
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)
    xdg = prepare_run(str(workdir),
                      _Cfg(str(sh), xdg=_base_xdg_with_providers(tmp_path),
                           exclude=["local-only"]))
    cfg = json.load(open(os.path.join(xdg, "opencode", "opencode.json"),
                         encoding="utf-8"))
    assert "local-only" not in cfg["provider"]
    assert "prod" in cfg["provider"]
    assert cfg["model"] == "prod/old"


def test_prepare_run_exclude_never_removes_default_model_provider(tmp_path):
    sh = tmp_path / "shared"
    (sh / "skills").mkdir(parents=True)
    workdir = tmp_path / "wd"
    (workdir / "home").mkdir(parents=True)
    xdg = prepare_run(str(workdir),
                      _Cfg(str(sh), xdg=_base_xdg_with_providers(tmp_path),
                           exclude=["prod", "local-only"]))
    cfg = json.load(open(os.path.join(xdg, "opencode", "opencode.json"),
                         encoding="utf-8"))
    assert "prod" in cfg["provider"]      # 默认模型所在 provider 保留
    assert "local-only" not in cfg["provider"]
