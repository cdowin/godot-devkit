"""The godot-ui skill installer: currentness, refusal, and root selection."""
from __future__ import annotations

from pathlib import Path

from godot_devkit.godot import skill_install


def _bundled(name: str) -> str:
    return {'SKILL.md': '# Bundled skill\n',
            'agents/openai.yaml': 'name: godot-ui\n'}[name]


def test_default_roots_check_and_idempotence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(skill_install, 'repo_root', lambda: tmp_path)
    codex = tmp_path / '.agents' / 'skills' / 'godot-ui'
    claude = tmp_path / '.claude' / 'skills' / 'godot-ui'

    assert skill_install.main(['--check']) == 1
    assert 'missing' in capsys.readouterr().out
    assert not codex.exists()
    assert skill_install.main([]) == 0
    capsys.readouterr()
    assert (codex / 'SKILL.md').read_text() == skill_install._source('SKILL.md')
    assert (codex / 'agents' / 'openai.yaml').read_text() == skill_install._source('agents/openai.yaml')
    before = {p: p.stat().st_mtime_ns for p in codex.rglob('*') if p.is_file()}
    assert skill_install.main([]) == 0
    assert 'already current' in capsys.readouterr().out
    assert {p: p.stat().st_mtime_ns for p in before} == before
    assert skill_install.main(['--check']) == 0
    capsys.readouterr()

    assert skill_install.main(['--runtime', 'claude']) == 0
    capsys.readouterr()
    assert (claude / 'SKILL.md').read_text() == skill_install._source('SKILL.md')
    assert (codex / 'SKILL.md').read_text() == skill_install._source('SKILL.md')


def test_collision_preflight_force_and_read_only_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(skill_install, '_source', _bundled)
    root = tmp_path / 'global-skills'
    skill = root / 'godot-ui'
    skill.mkdir(parents=True)
    prior = skill / 'SKILL.md'
    prior.write_text('# Personal changes\n')

    assert skill_install.main(['--dest', str(root)]) == 1
    assert 'nothing was written' in capsys.readouterr().err
    assert prior.read_text() == '# Personal changes\n'
    assert not (skill / 'agents' / 'openai.yaml').exists()

    assert skill_install.main(['--dest', str(root), '--check', '--diff']) == 1
    output = capsys.readouterr().out
    assert '--- a/godot-ui/SKILL.md' in output
    assert 'missing' in output
    assert prior.read_text() == '# Personal changes\n'
    assert not (skill / 'agents' / 'openai.yaml').exists()

    assert skill_install.main(['--dest', str(root), '--force']) == 0
    capsys.readouterr()
    assert prior.read_text() == _bundled('SKILL.md')
    assert (skill / 'agents' / 'openai.yaml').read_text() == _bundled('agents/openai.yaml')


def test_defects_and_symlink_never_write_or_follow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(skill_install, '_source', _bundled)
    root = tmp_path / 'skills'
    skill = root / 'godot-ui'
    skill.mkdir(parents=True)
    elsewhere = tmp_path / 'elsewhere.md'
    elsewhere.write_text('# Keep this\n')
    (skill / 'SKILL.md').symlink_to(elsewhere)

    assert skill_install.main(['--dest', str(root), '--force']) == 1
    assert 'symlink' in capsys.readouterr().err
    assert elsewhere.read_text() == '# Keep this\n'
    assert not (skill / 'agents' / 'openai.yaml').exists()
    assert skill_install.main(['--dest', str(root), '--check']) == 1
    capsys.readouterr()
    assert elsewhere.read_text() == '# Keep this\n'

    (skill / 'SKILL.md').unlink()
    (skill / 'SKILL.md').mkdir()
    assert skill_install.main(['--dest', str(root), '--force']) == 1
    assert 'directory' in capsys.readouterr().err
    assert not (skill / 'agents' / 'openai.yaml').exists()


def test_symlinked_skill_directories_refuse_but_selected_root_may_be_symlink(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(skill_install, '_source', _bundled)
    for directory in ('godot-ui', 'agents'):
        root = tmp_path / directory / 'skills'
        skill = root / 'godot-ui'
        outside = tmp_path / directory / 'outside'
        outside.mkdir(parents=True)
        if directory == 'godot-ui':
            root.mkdir(parents=True)
            skill.symlink_to(outside, target_is_directory=True)
            protected = outside / 'SKILL.md'
        else:
            skill.mkdir(parents=True)
            (skill / 'agents').symlink_to(outside, target_is_directory=True)
            protected = outside / 'openai.yaml'
        protected.write_text('personal content\n')

        assert skill_install.main(['--dest', str(root), '--force']) == 1
        assert 'symlink below the skills root' in capsys.readouterr().err
        assert protected.read_text() == 'personal content\n'
        if directory == 'agents':
            assert not (skill / 'SKILL.md').exists()

    selected = tmp_path / 'selected-skills'
    selected.mkdir()
    link = tmp_path / 'explicit-root-link'
    link.symlink_to(selected, target_is_directory=True)
    assert skill_install.main(['--dest', str(link)]) == 0
    capsys.readouterr()
    assert (selected / 'godot-ui' / 'SKILL.md').read_text() == _bundled('SKILL.md')


def test_usage_refuses_unknown_runtime_and_check_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(skill_install, '_source', _bundled)
    for argv in (['--runtime', 'unknown', '--dest', str(tmp_path)],
                 ['--check', '--force', '--dest', str(tmp_path)],
                 ['--dest']):
        assert skill_install.main(argv) == 2
        capsys.readouterr()
    assert list(tmp_path.iterdir()) == []
