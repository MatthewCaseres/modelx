import modelx as mx
import pytest


def test_change_attrref():

    m = mx.new_model()
    s = m.new_space()

    @mx.defcells
    def foo(x):
        return bar.x

    @mx.defcells
    def qux(y):
        return bar[1].x

    s2 = mx.new_space("bar", formula=lambda a: None)
    s.bar = s2

    s2.x = "bar"
    assert foo(3) == qux(3) == "bar"

    s2.x = "baz"
    assert foo(3) == qux(3) == "baz"


def test_del_global_attrref():
    """
    m-----SpaceA-----foo
       +--SpaceB  +--s2
       +--x
    """
    m = mx.new_model()
    s = mx.new_space("SpaceA")

    @mx.defcells
    def foo(i):
        return s2.x

    s2 = mx.new_space(name="SpaceB", formula=lambda a: None)
    s.s2 = s2
    m.x = 3
    assert foo(3) == 3
    del m.x

    with pytest.raises(AttributeError):
        foo(3)


def test_del_attrref():
    """
    m-----SpaceA-----SpaceB---x
       |     +----foo
       +--SpaceC(SpaceA)
    """

    m = mx.new_model()
    A = m.new_space("SpaceA")
    B = A.new_space("SpaceB")
    B.x = 3

    def foo():
        return SpaceB.x

    A.new_cells(formula=foo)
    C = m.new_space("SpaceC", bases=A)

    assert A.foo() == 3
    assert C.foo() == 3

    del B.x

    with pytest.raises(AttributeError):
        A.foo()

    with pytest.raises(AttributeError):
        C.foo()
