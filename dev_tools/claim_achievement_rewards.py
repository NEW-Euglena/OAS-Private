"""单独领取当前登录角色已经达成的成就奖励，完成后返回庭院。"""

import argparse
from multiprocessing import freeze_support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='oas1', help='读取设备设置的 OAS 配置名，默认 oas1')
    args = parser.parse_args()

    from module.config.config import Config
    from module.device.device import Device
    from module.image.rpc import ensure_image_server_ready
    from module.logger import logger
    from module.ocr.rpc import ensure_ocr_server_ready
    from tasks.LevelRush.script_task import ScriptTask

    logger.set_file_logger('claim_achievement_rewards')
    try:
        config = Config(args.config)
        logger.info(f'[临时领奖] 使用 {args.config} 的设备设置，领取当前登录角色的成就奖励')
        ensure_image_server_ready()
        ensure_ocr_server_ready()
        device = Device(config)
        task = ScriptTask(config=config, device=device)
        task.get_achievement_reward()
        logger.info('[临时领奖] 本次成就奖励领取结束，已返回庭院')
        return 0
    except KeyboardInterrupt:
        logger.info('[临时领奖] 已手动停止')
        return 130
    except Exception:
        logger.exception('[临时领奖] 领取失败，请检查模拟器及游戏界面')
        return 1


if __name__ == '__main__':
    freeze_support()
    raise SystemExit(main())
