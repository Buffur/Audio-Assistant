from pathlib import Path

import pytest

from utils import audio


def test_build_smooth_concat_filter_uses_loudnorm_and_crossfade() -> None:
    filter_graph, output_label = audio._build_smooth_concat_filter(
        files_count=3,
        crossfade_ms=80,
    )

    assert output_label == "[out]"
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in filter_graph
    assert "acrossfade=d=0.080:c1=tri:c2=tri" in filter_graph
    assert filter_graph.count("acrossfade=") == 2


@pytest.mark.asyncio
async def test_concat_ogg_files_uses_ffmpeg_concat(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    input_one = workspace_tmp_path / "one.ogg"
    input_two = workspace_tmp_path / "two.ogg"
    input_one.write_bytes(b"one")
    input_two.write_bytes(b"two")
    commands = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command) -> None:
            self.command = command

        async def communicate(self):
            Path(self.command[-1]).write_bytes(b"joined")
            return b"", b""

        def kill(self) -> None:
            pass

    async def fake_create_subprocess_exec(*command, **kwargs):
        commands.append(command)
        return FakeProcess(command)

    monkeypatch.setattr(audio, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        audio.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await audio.concat_ogg_files([str(input_one), str(input_two)])

    assert Path(result).read_bytes() == b"joined"
    assert len(commands) == 1
    assert commands[0][:8] == (
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
    )
    assert "-c" in commands[0]
    assert "copy" in commands[0]

    Path(result).unlink()


@pytest.mark.asyncio
async def test_concat_ogg_files_smooth_uses_filter_script(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    input_one = workspace_tmp_path / "one.ogg"
    input_two = workspace_tmp_path / "two.ogg"
    input_one.write_bytes(b"one")
    input_two.write_bytes(b"two")
    commands = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command) -> None:
            self.command = command

        async def communicate(self):
            Path(self.command[-1]).write_bytes(b"smooth")
            return b"", b""

        def kill(self) -> None:
            pass

    async def fake_create_subprocess_exec(*command, **kwargs):
        commands.append(command)
        return FakeProcess(command)

    monkeypatch.setattr(audio, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        audio.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await audio.concat_ogg_files(
        [str(input_one), str(input_two)],
        smooth=True,
        crossfade_ms=80,
    )

    assert Path(result).read_bytes() == b"smooth"
    assert len(commands) == 1
    assert "-filter_complex_script" in commands[0]
    assert "-map" in commands[0]
    assert "[out]" in commands[0]
    assert "libopus" in commands[0]

    Path(result).unlink()


@pytest.mark.asyncio
async def test_concat_ogg_files_reencodes_when_stream_copy_fails(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    input_one = workspace_tmp_path / "one.ogg"
    input_two = workspace_tmp_path / "two.ogg"
    input_one.write_bytes(b"one")
    input_two.write_bytes(b"two")
    commands = []

    class FakeProcess:
        def __init__(self, command, returncode: int) -> None:
            self.command = command
            self.returncode = returncode

        async def communicate(self):
            if self.returncode == 0:
                Path(self.command[-1]).write_bytes(b"reencoded")

            return b"", b"copy failed"

        def kill(self) -> None:
            pass

    async def fake_create_subprocess_exec(*command, **kwargs):
        commands.append(command)
        return FakeProcess(command, returncode=1 if len(commands) == 1 else 0)

    monkeypatch.setattr(audio, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        audio.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await audio.concat_ogg_files([str(input_one), str(input_two)])

    assert Path(result).read_bytes() == b"reencoded"
    assert len(commands) == 2
    assert "copy" in commands[0]
    assert "libopus" in commands[1]

    Path(result).unlink()
