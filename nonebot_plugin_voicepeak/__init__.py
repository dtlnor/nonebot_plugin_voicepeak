import traceback
import os
import asyncio
from datetime import datetime
import time
from typing import Tuple, Union, Any
import re


import nonebot
from nonebot import Driver, on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent,  Message, MessageSegment, MessageEvent
from nonebot.params import ArgStr, CommandArg, RegexGroup
from nonebot.typing import T_State
from nonebot.log import logger
from nonebot.exception import FinishedException

from configs.config import Config

# from .data_source import get_reply

__zx_plugin_name__ = "nonebot_plugin_voicepeak"
__plugin_des__ = "调用 voicepeak 生成语音"
__plugin_cmd__= ["{角色}说 {参数}{数值} {内容}"]
__plugin_usage__ = __plugin_des__+R"""

参数：
——速度：100 是默认值，范围是 50~200
——音高：0 是默认值，范围是 -300~300
——{感情}：0 是默认值，范围是 0~100

目前可用角色与感情为
"""+ "\n".join( [ "——"+n+": ["+",".join(list(emos['emotion'].values()))+"]" for n, emos in Config.get_config("nonebot_plugin_voicepeak", "NARRATOR").items()])+R"""

示例：星界说 音高80 悲伤100 私、いらないんでしょ

注：文本不能换行。不能超过140字
参数可以任意数量混搭（e.g.开心100 悲伤100 速度100）
参数前后必须有空格（正确：开心100 幸福50。错误：开心100幸福50）"""

__plugin_settings__= {
    "level": 5,
    "cmd": ["{说话人}说"],
    "default_status": True,     # 进群时的默认开关状态
}

__plugin_type__ = ("一些工具",)
__plugin_version__ = 0.1
__plugin_author__ = "dtlnor"
# __plugin_resources__ = None
__plugin_configs__ = {
    "VP_PATH": {
        "value": os.path.join(os.environ["ProgramFiles"], "VOICEPEAK", "voicepeak.exe"),
        "help": "voicepeak.exe 的完整路径",
        "default_value": os.path.join(os.environ["ProgramFiles"], "VOICEPEAK", "voicepeak.exe")
    },
    "NARRATOR": {
        "value": {
            "星界": {
                "name":"SEKAI",
                "emotion":{
                    "happy":"幸福",
                    "sad":"(悲伤|悲傷)",
                    "fun":"(快乐|快樂)",
                    "angry":"(愤怒|憤怒)",
                },
            },
        },
        "help": "說話人",
        "default_value": {
            "星界": {
                "name":"SEKAI",
                "emotion":{
                    "happy":"幸福",
                    "sad":"(悲伤|悲傷)",
                    "fun":"(快乐|快樂)",
                    "angry":"(愤怒|憤怒)",
                },
            },
        }
    }
}

__plugin_cd_limit__ = {
    "cd": 300,                # 限制 cd 时长
    "check_type": "all",    # 'private'/'group'/'all'，限制私聊/群聊/全部
    "limit_type": "user",   # 监听对象，以user_id或group_id作为键来限制，'user'：用户id，'group'：群id
    "rst": "[at] 你先别急，用太多会风控，请稍后再用。（去 dlsite 自己买一份功能更多哦）",            # 回复的话，为None时不回复，可以添加[at]，[uname]，[nickname]来对应艾特，用户群名称，昵称系统昵称
    "status": True          # 此限制的开关状态
}

__plugin_count_limit__ = {
    "max_count": 10,
    "rst": "[at] 今天暂时用不了了！考虑去 dlsite 买一份吗？"
}

vpgen = on_regex(
    r'^\s*(?:('+"|".join(list(Config.get_config("nonebot_plugin_voicepeak", "NARRATOR").keys()))+r')|[vV][pP])[说說]\s+(.*)', priority=5, block=True
)

vpdes = on_regex(
    r'^\s*(?:('+"|".join(list(Config.get_config("nonebot_plugin_voicepeak", "NARRATOR").keys()))+r')|[vV][pP])[说說]明', priority=5, block=True
)

@vpgen.handle()
async def _(reg_group: Tuple[Any, ...] = RegexGroup()):
    emotion = {}
    speed = None
    pitch = None
    narrator_info: dict = Config.get_config("nonebot_plugin_voicepeak", "NARRATOR")
    try:
        if not reg_group:
            await vpgen.finish()

        if not os.path.exists(Config.get_config("nonebot_plugin_voicepeak", "VP_PATH")):
            await vpgen.finish("找不到 voicepeak.exe")

        narrator: str = reg_group[0]
        if narrator is None:
            narrator = list(narrator_info.keys())[0] # default to first narrator
        
        logger.info(reg_group)
        cmd = reg_group[1] # content with tag
        if not cmd:
            await vpgen.finish()
        
        text = cmd
        for emo_param, emo_match in narrator_info[narrator]['emotion'].items():
            grp = re.match(r".*"+emo_match+r"\s*(\d+)\s+(.*)", cmd)
            if grp is not None:
                emotion = emotion | {emo_param: int(grp[1])}
                if len(text) > len(grp[2]):
                    # get shortest remaining text as text content.
                    text = grp[2]
        
        for _, v in emotion.items():
            if not 0 <= v <= 100:
                await vpgen.finish("感情参数需要在0~100之间")

        emotion = emotion if len(emotion.keys()) > 0 else None

        speedGrp = re.match(r".*速度\s*(-?\d+)\s+(.*)", cmd)
        speed = int(speedGrp[1]) if speedGrp is not None else None
        if speed is not None and not 50 <= speed <= 200:
            await vpgen.finish("速度参数需要在50~200之间")
        
        pitchGrp = re.match(r".*音高\s*(-?\d+)\s+(.*)", cmd)
        pitch = int(pitchGrp[1]) if pitchGrp is not None else None
        if pitch is not None and not -300 <= pitch <= 300:
            await vpgen.finish("音高参数需要在-300~300之间")

        for grp in [speedGrp, pitchGrp]:
            if grp is not None:
                if len(text) > len(grp[2]):
                    text = grp[2]

        text = text.strip().replace('\r\n','　').replace('\n','　').replace(',','、').replace('，','、').replace(' ','　')
        if len(text) > 140:
            await vpgen.finish("文本长度不能超过140字")

        logger.debug("vp say - ", text)

        filename = f"{str(datetime.now()).replace(':','.').replace(' ','_')}.wav"
        output_path = os.path.join(Config.get_config("nonebot_plugin_voicepeak", "VP_PATH").removesuffix("\\voicepeak.exe"),"output", filename)
        logger.debug(output_path)

        await say_text(
            narrator=narrator_info[narrator]['name'],
            text=text,
            output_path=output_path,
            emotions=emotion,
            speed=speed,
             pitch=pitch)
        await vpgen.send(MessageSegment.record(f"file:///{output_path}"))
    except RuntimeError as e:
        if 'up to 1 command line instance' in str(e):
            await vpgen.send("撞车了，当前程序正在生成其他语音")
        else:
            logger.warning(traceback.format_exc())
            await vpgen.send("出错了，请稍后再试")
            
    except Exception as e:
        if isinstance(e, FinishedException):
            pass
        else:
            logger.warning(traceback.format_exc())
            await vpgen.send("出错了，请稍后再试")


@vpdes.handle()
async def _():
    await vpdes.send(__plugin_usage__)

### modified from https://github.com/Nanahuse/VoicepeakWrapper
def __make_say_command(
    text: str | None = None,
    output_path: str | None = None,
    narrator: str | None = None,
    emotions: dict[str, int] | None = None,
    speed: int | None = None,
    pitch: int | None = None,
) -> str:

    if not text:
        raise ValueError("no text inside")

async def say_text(
    text: str,
    *,
    output_path: str | None = None,
    narrator: str | None = None,
    emotions: dict[str, int] | None = None,
    speed: int | None = None,
    pitch: int | None = None,
):
    command = list()

    command.append(f'-s "{text}"')

    if output_path is not None:
        command.append(f'-o "{output_path}"')

    if narrator is not None:
        command.append(f'-n "{narrator}"')

    if emotions is not None:
        command.append(f'-e {",".join(f"{param}={value}" for param, value in emotions.items())}')

    if speed is not None:
        command.append(f"--speed {speed}")
    if pitch is not None:
        command.append(f"--pitch {pitch}")

    cmd = " ".join(command)
    
    logger.debug(f'"{Config.get_config("nonebot_plugin_voicepeak", "VP_PATH")}" {cmd}')

    proc = await asyncio.create_subprocess_shell(
        f'"{Config.get_config("nonebot_plugin_voicepeak", "VP_PATH")}" {cmd}',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if len(stderr) != 0:
        error_message = stderr.decode()
        raise RuntimeError(error_message)

    return stdout.decode()
