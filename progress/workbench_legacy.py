"""旧标记迁移已退役；既有 legacy 归档保留，不读取或写入旧数据。

保留旧入口作为明确拒绝的 tombstone，不再提供规划、迁移、确认或归档能力。
新工作台状态独立管理，旧 done 标记不会提升审核结论。
"""
import sys

from workbench_store import StoreError


RETIRED_MESSAGE = '旧标记迁移已停用（retired）；已有 legacy 归档仅保留，不读取、不迁移、不确认、不写入。'


class RetiredError(StoreError):
    """旧迁移入口已退役，且未访问调用方数据。"""


def plan(root, raw):
    raise RetiredError(RETIRED_MESSAGE)


def publish(path, payload):
    raise RetiredError(RETIRED_MESSAGE)


def migrate(root, source, private):
    raise RetiredError(RETIRED_MESSAGE)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args in (['--help'], ['-h']):
        print(RETIRED_MESSAGE)
        return 0
    print(RETIRED_MESSAGE, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
