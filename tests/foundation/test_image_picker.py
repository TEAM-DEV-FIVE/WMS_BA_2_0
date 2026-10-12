from types import SimpleNamespace
from unittest.mock import Mock

from apps.desktop.views import image_picker


def parent():
    return SimpleNamespace(grab_release=Mock(), grab_set=Mock(), lift=Mock(),
                           after=Mock(return_value="timer"), after_cancel=Mock(), winfo_exists=lambda: True)


def test_native_selection_preserves_spaces_and_cancel_does_not_fallback(monkeypatch):
    monkeypatch.setattr(image_picker.sys, "platform", "linux")
    monkeypatch.setattr(image_picker.shutil, "which", lambda name: "/usr/bin/zenity")
    for code, output, expected in [(0, "/tmp/ảnh của tôi.png\n", "/tmp/ảnh của tôi.png"), (1, "", "")]:
        process = Mock(returncode=code)
        process.poll.return_value = code
        process.communicate.return_value = (output, None)
        launch = Mock(return_value=process)
        monkeypatch.setattr(image_picker.subprocess, "Popen", launch)
        selected = Mock()
        picker = image_picker.ImagePicker(parent(), selected)
        picker.fallback = Mock()
        picker.start()
        selected.assert_called_once_with(expected)
        picker.fallback.assert_not_called()
        assert not launch.call_args.kwargs.get("shell", False)
        picker.parent.grab_set.assert_called_once()


def test_closing_profile_stops_picker_without_selection(monkeypatch):
    selected = Mock()
    picker = image_picker.ImagePicker(parent(), selected)
    process = Mock()
    process.poll.return_value = None
    picker.process = process
    picker.poll()
    picker.cancel()
    picker.poll()
    picker.parent.after_cancel.assert_called_once_with("timer")
    process.terminate.assert_called_once()
    selected.assert_not_called()
    assert picker.process is None


def test_default_folder_prefers_pictures_then_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(image_picker.Path, "home", lambda: tmp_path)
    assert image_picker.image_directory() == tmp_path
    (tmp_path / "Downloads").mkdir()
    assert image_picker.image_directory() == tmp_path / "Downloads"
    (tmp_path / "Pictures").mkdir()
    assert image_picker.image_directory() == tmp_path / "Pictures"
