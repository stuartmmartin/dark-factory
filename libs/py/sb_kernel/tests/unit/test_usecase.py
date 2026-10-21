"""Use cases satisfy the callable port structurally, without inheriting platform machinery."""

from sb_kernel.usecase import UseCase


class Increment:
    async def __call__(self, command: int) -> int:
        return command + 1


async def test_callable_implements_the_generic_port() -> None:
    use_case: UseCase[int, int] = Increment()
    assert await use_case(4) == 5
