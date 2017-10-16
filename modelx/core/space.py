from collections import Sequence
from textwrap import dedent
from types import (MappingProxyType,
                   FunctionType)

from modelx.core.base import (ObjectArgs,
                              get_impls,
                              get_interfaces,
                              Impl,
                              Interface,
                              LazyEvalDict,
                              LazyEvalChainMap)
from modelx.core.formula import Formula, create_closure
from modelx.core.cells import Cells, CellsImpl
from modelx.core.util import AutoNamer, is_valid_name, get_module


class SpaceArgs(ObjectArgs):
    """Combination of space and arguments to locate its subspace."""

    def __init__(self, space, args, kwargs=None):

        ObjectArgs.__init__(self, space, args, kwargs)
        self.space = self.obj_

    def eval_formula(self):

        func = self.space.paramfunc.func
        codeobj = func.__code__
        name = self.space.name
        namespace = self.space.namespace

        closure = func.__closure__  # None normally.
        if closure is not None:     # pytest fails without this.
            closure = create_closure(self.space.interface)

        altfunc = FunctionType(codeobj, namespace,
                               name=name, closure=closure)

        return altfunc(**self.arguments)


class ParamFunc(Formula):
    def __init__(self, func):
        Formula.__init__(self, func)


class SpaceContainerImpl(Impl):
    """Base class of Model and Space that contain spaces."""

    state_attrs = ['_spaces',
                   'param_spaces',
                   'spacenamer',
                   'paramfunc'] + Impl.state_attrs

    def __init__(self, system, if_class, paramfunc):

        Impl.__init__(self, if_class)

        self.system = system
        self.param_spaces = {}
        self.spacenamer = AutoNamer('Space')

        if paramfunc is None:
            self.paramfunc = None
        else:
            self.paramfunc = ParamFunc(paramfunc)

        self._spaces = {}

    def __getstate__(self):

        state = {key: value for key, value in self.__dict__.items()
                 if key in self.state_attrs}

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def restore_state(self, system):
        """Called after unpickling to restore some attributes manually."""

        self.system = system

        for space in self._spaces.values():
            space.restore_state(system)

    @property
    def spaces(self):
        return self._spaces

    def has_space(self, name):
        return name in self.spaces

    def new_space(self, *, name=None, bases=None, paramfunc=None,
                     arguments=None):
        """Create a child space.

        Args:
            name (str): Name of the space. If omitted, the space is
                created automatically.
            bases: If specified, the new space becomes a derived space of
                the `base` space.
            paramfunc: Function whose parameters used to set space parameters.
            arguments: ordered dict of space parameter names to their values.
            base_self: True if subspaces inherit self by default.

        """
        space = SpaceImpl(parent=self, name=name, bases=bases,
                          paramfunc=paramfunc, arguments=arguments)



        return space

    def new_space_from_module(self, module_, recursive=False, **params):

        module_ = get_module(module_)

        if 'name' not in params or params['name'] is None:
            name = params['name'] = module_.__name__.split('.')[-1] # xxx.yyy.zzz -> zzz
        else:
            name = params['name']

        space = self.new_space(**params)
        space.new_cells_from_module(module_)

        if recursive and hasattr(module_, '_spaces'):
            for name in module_._spaces:
                submodule = module_.__name__ + '.' + name
                space.new_space_from_module(module_=submodule,
                                               recursive=True)

        return space

    def new_space_from_excel(self, book, range_, sheet=None,
                                name=None,
                                names_row=None, param_cols=None,
                                space_param_order=None,
                                cells_param_order=None,
                                transpose=False,
                                names_col=None, param_rows=None):

        import modelx.io.excel as xl

        param_order = space_param_order + cells_param_order

        cellstable = xl.CellsTable(book, range_, sheet,
                                   names_row, param_cols,
                                   param_order,
                                   transpose,
                                   names_col, param_rows)

        space_params = cellstable.param_names[:len(space_param_order)]
        cells_params = cellstable.param_names[len(space_param_order):]

        if space_params:
            space_sig = "=None, ".join(space_params) + "=None"
        else:
            space_sig = ""

        if cells_params:
            cells_sig = "=None, ".join(cells_params) + "=None"
        else:
            cells_sig = ""

        param_func = "def _param_func(" + space_sig + "): pass"
        blank_func = "def _blank_func(" + cells_sig + "): pass"

        space = self.new_space(name=name, paramfunc=param_func)

        for cellsdata in cellstable.items():
            for args, value in cellsdata.items():
                space_args = args[:len(space_params)]
                cells_args = args[len(space_params):]

                subspace = space.get_space(space_args)

                if cellsdata.name in subspace.cells:
                    cells = subspace.cells[cellsdata.name]
                else:
                    cells = subspace.new_cells(name=cellsdata.name,
                                                  func=blank_func)
                cells.set_value(cells_args, value)

        return space

    def get_space(self, args, kwargs=None):

        ptr = SpaceArgs(self, args, kwargs)

        if ptr.argvalues in self.param_spaces:
            return self.param_spaces[ptr.argvalues]

        else:
            last_self = self.system.self
            self.system.self = self

            try:
                space_args = ptr.eval_formula()

            finally:
                self.system.self = last_self

            if space_args is None:
                space_args = {}
            else:
                space_args = get_impls(space_args)

            space_args['arguments'] = ptr.arguments
            space = self.new_space(**space_args)
            self.param_spaces[ptr.argvalues] = space
            return space

    def set_paramfunc(self, paramfunc):
        if self.paramfunc is None:
            self.paramfunc = ParamFunc(paramfunc)
        else:
            raise ValueError("paramfunc already assigned.")


class SpaceContainer(Interface):
    """A common base class shared by Model and Space.

    A base class for implementing (sub)space containment.
    """
    def new_space(self, name=None, bases=None, paramfunc=None):
        """Create a (sub)space.

        Args:
            name (str, optional): Name of the space. Defaults to ``SpaceN``,
                where ``N`` is a number determined automatically.
            bases (optional): A space or a sequence of spaces to be the base
                space(s) of the created space.
            paramfunc (optional): Function to specify the parameters of
                dynamic (sub)spaces. The signature of this function is used
                for setting parameters for dynamic (sub)spaces.
                This function should return a mapping of keyword arguments
                to be passed to this method when the dynamic (sub)spaces
                are created.

        Returns:
            The new (sub)space.
        """
        space = self._impl.model.currentspace \
            = self._impl.new_space(name=name, bases=get_impls(bases),
                                      paramfunc=paramfunc)

        return space.interface

    def new_space_from_module(self, module_, recursive=False, **params):
        """Create a (sub)space from an module.

        Args:
            module_: a module object or name of the module object.
            recursive: Not yet implemented.
            **params: arguments to pass to ``new_space``

        Returns:
            The new (sub)space created from the module.
        """

        space = self._impl.model.currentspace \
            = self._impl.new_space_from_module(module_,
                                                  recursive=recursive,
                                                  **params)

        return get_interfaces(space)

    def new_space_from_excel(self, book, range_, sheet=None,
                                name=None,
                                names_row=None, param_cols=None,
                                space_param_order=None,
                                cells_param_order=None,
                                transpose=False,
                                names_col=None, param_rows=None):
        """Create a (sub)space from an Excel range.

        To use this method, ``openpyxl`` package must be installed.

        Args:
            book (str): Path to an Excel file.
            range_ (str): Range expression, such as "A1", "$G4:$K10",
                or named range "NamedRange1".
            sheet (str): Sheet name (case ignored).
            name (str, optional): Name of the space. Defaults to ``SpaceN``,
                where ``N`` is a number determined automatically.
            names_row (optional): an index number indicating
                what row contains the names of cells and parameters.
                Defaults to the top row (0).
            param_cols (optional): a sequence of index numbers
                indicating parameter columns.
                Defaults to only the leftmost column ([0]).
            names_col (optional): an index number, starting from 0,
                indicating what column contains additional parameters.
            param_rows (optional): a sequence of index numbers, starting from
                0, indicating rows of additional parameters, in case cells are
                defined in two dimensions.
            transpose (optional): Defaults to ``False``.
                If set to ``True``, "row(s)" and "col(s)" in the parameter
                names are interpreted inversely, i.e.
                all indexes passed to "row(s)" parameters are interpreted
                as column indexes,
                and all indexes passed to "col(s)" parameters as row indexes.
            space_param_order: a sequence to specify space parameters and
                their orders. The elements of the sequence denote the indexes
                of ``param_cols`` elements, and optionally the index of
                ``param_rows`` elements shifted by the length of
                ``param_cols``. The elements of this parameter and
                ``cell_param_order`` must not overlap.
            cell_param_order (optional): a sequence to reorder the parameters.
                The elements of the sequence denote the indexes of
                ``param_cols`` elements, and optionally the index of
                ``param_rows`` elements shifted by the length of
                ``param_cols``. The elements of this parameter and
                ``cell_space_order`` must not overlap.

        Returns:
            The new (sub)space created from the Excel range.
        """

        space = self._impl.new_space_from_excel(
            book, range_, sheet, name,
            names_row, param_cols,
            space_param_order,
            cells_param_order,
            transpose,
            names_col, param_rows)

        return get_interfaces(space)

    @property
    def spaces(self):
        """A mapping of the names of (sub)spaces to the Space objects"""
        return MappingProxyType(get_interfaces(self._impl.spaces))


class ImplMap:
    """Base class"""
    def __init__(self):
        self._interfaces = {}
        self.interfaces = MappingProxyType(self._interfaces)

    def _update_interfaces(self):
        self._interfaces.clear()
        self._interfaces.update(get_interfaces(self))

    def __getstate__(self):
        state = {key: value for key, value in self.__dict__.items()}
        del state['interfaces']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.interfaces = MappingProxyType(self._interfaces)


class BaseMembers(LazyEvalDict):
    """Members of bases to be inherited to ``space``"""

    def __init__(self, derived):

        observer = [derived]
        LazyEvalDict.__init__(self, {}, observer)

        self.space = derived.space
        self.member = derived.member

        attr = 'self_' + self.member
        observe = []
        for base in self.space.mro[1:]:
            base._self_members.append_observer(self)

        self.update_data()

    def _update_data(self):

        self.data.clear()
        bases = list(reversed(self.space.mro))

        for base, base_next in zip(bases, bases[1:]):

            attr = 'self_' + self.member
            self.data.update(getattr(base, attr))
            keys = self.data.keys() - base_next.self_members.keys()

            for name in list(self.data):
                if name not in keys:
                    del self.data[name]

class DerivedMembers(LazyEvalDict):

    def __init__(self, space, data=None, observers=None, member=''):

        if data is None:
            data = {}
        if observers is None:
            observers = []

        self.space = space
        self.member = member
        LazyEvalDict.__init__(self, data, observers)
        self._base_members = BaseMembers(self)
        self.update_data()

    @property
    def base_members(self):
        return self._base_members.update_data()

    def _update_data(self):
        if self.member == 'cells':
            self._update_data_cells()
        elif self.member == 'spaces':
            self._update_data_spaces()
        elif self.member == 'refs':
            self._update_data_refs()
        else:
            raise ValueError

    def _update_data_cells(self):

        keys = self.data.keys() - self.base_members.keys()

        for key in keys:
            del self.data[key]

        for key, base_cell in self.base_members.items():

            if key in self.data:
                if self.data[key].formula is base_cell.formula:
                    return
                else:
                    del self.data[key]

            cell = CellsImpl(space=self.space, name=base_cell.name,
                             func=base_cell.formula)

            self.data[key] = cell

    def _update_data_spaces(self):

        self.data.clear()
        for base_space in self.base_members.values():

            space = SpaceImpl(parent=self.space, name=base_space.name,
                              bases=base_space.direct_bases,
                              paramfunc=base_space.paramfunc)

            self.data[space.name] = space

    def _update_data_refs(self):

        self.data.clear()
        self.data.update(self.base_members)


class ImplDerivedMembers(ImplMap, DerivedMembers):

    def __init__(self, space, data=None, observers=None, member=''):
        ImplMap.__init__(self)
        DerivedMembers.__init__(self, space, data, observers, member)

    def _update_data(self):
        DerivedMembers._update_data(self)
        self._update_interfaces()


class SelfMembers(LazyEvalDict):

    def __init__(self, space, attr, data=None, observers=None):

        if data is None:
            data = {}
        if observers is None:
            observers = []

        LazyEvalDict.__init__(self, data, observers)
        self.space = space
        self.attr = attr


class ImplSelfMembers(ImplMap, SelfMembers):

    def __init__(self, space, attr, data=None, observers=None):
        ImplMap.__init__(self)
        SelfMembers.__init__(self, space, attr, data, observers)

    def _update_data(self):
        self._update_interfaces()


class ImplChainMap(ImplMap, LazyEvalChainMap):

    def __init__(self, maps=None, observers=None, observe_maps=True):
        ImplMap.__init__(self)
        LazyEvalChainMap.__init__(self, maps, observers, observe_maps)

    def _update_data(self):
        LazyEvalChainMap._update_data(self)
        self._update_interfaces()


class NameSpaceDict(LazyEvalDict):

    def __init__(self, space, data=None, observers=None):

        if data is None:
            data = {}
        if observers is None:
            observers = []

        LazyEvalDict.__init__(self, data, observers)
        self.space = space

    def _update_data(self):
        _ = self.space.namespace_impl
        self.data.clear()
        self.data.update(get_interfaces(self.space.cells))
        self.data.update(get_interfaces(self.space.spaces))
        self.data.update(self.space.refs)


class SpaceImpl(SpaceContainerImpl):
    """The implementation of Space class.

    The rationales for splitting implementation from its interface are twofold,
    one is to hide from users attributes used only within the package,
    and the other is to free referring objects from getting affected by
    special methods that are meant for changing the behaviour of operations
    for users.

    namespace

        cells
            derived_cells
            self_cells

        spaces
            dynamic_spaces
            static_spaces
                derived_spaces
                self_spaces

        refs
            derived_refs
            self_refs
            global_refs
            arguments

        cells_parameters (Not yet implemented)

    derived_members (ChainMap)
        derived_cells
        derived_spaces
        derived_refs

    self_members
        self_cells
        self_spaces
        self_refs

        # Operations
        remove_derived
        revert_derived

    Args:
        parent: SpaceImpl or ModelImpl to contain this.
        name: Name of the space.
        params: Callable or str or sequence.
        bases: SpaceImpl or a list of SpaceImpl.
        
    Attributes:
        space (Space): The Space associated with this implementation.
        parent: the space or model containing this space.
        name:   name of this space.
        signature: Function signature for child spaces. None if not specified.
        
        cells (dict):  Dict to contained cells
        _self_cells (dict): cells defined in this space.
        base_cells (dict): cells in base spaces to inherit in this space.
        _derived_cells (dict): cells derived from base cells.
        _self_refs
        _derived_refs
        
        cellsnamer (AutoNamer): AutoNamer to auto-name unnamed child cells.
        
        mro (list): MRO of base spaces.
                
        _namespace (dict)
    """
    def __init__(self, parent, name, bases, paramfunc, arguments=None):

        if name is None:
            name = parent.spacenamer.get_next(parent.spaces)

        if parent.has_space(name):
            raise ValueError("Name already assigned.")

        if not is_valid_name(name):
            raise ValueError("Invalid name '%s'." % name)

        SpaceContainerImpl.__init__(self, parent.system, if_class=Space,
                                    paramfunc=paramfunc)

        self.name = name
        self.parent = parent
        self.cellsnamer = AutoNamer('Cells')

        if arguments is None:
            self._arguments = LazyEvalDict()
        else:
            self._arguments = LazyEvalDict(arguments)

        # Set up direct base spaces and mro
        if bases is None:
            self.direct_bases = []
        elif isinstance(bases, SpaceImpl):
            self.direct_bases = [bases]
        elif isinstance(bases, Sequence) \
                and all(isinstance(base, SpaceImpl) for base in bases):
            self.direct_bases = list(bases)
        else:
            raise TypeError('bases must be space(s).')

        self.mro = []
        self._update_mro()
        self._init_members()

        if isinstance(self.parent, SpaceImpl):
            if self.is_dynamic():
                parent._dynamic_spaces[self.name] = self
            else:
                parent._static_spaces[self.name] = self
        else:
            parent.spaces[self.name] = self

    def _init_members(self):

        self._self_cells = ImplSelfMembers(self, 'cells')
        self._self_spaces = ImplSelfMembers(self, 'spaces')
        self._dynamic_spaces = LazyEvalDict()
        self._self_refs = SelfMembers(self, 'refs')

        self_members = [self._self_cells,
                        self._self_spaces,
                        self._self_refs,
                        self._dynamic_spaces]

        # Add observers later to avoid circular reference
        self._self_members = LazyEvalChainMap(self_members)

        self._derived_cells = ImplDerivedMembers(self, member='cells')
        self._cells = ImplChainMap([self._self_cells,
                                    self._derived_cells])


        self._derived_spaces = ImplDerivedMembers(self, member='spaces')
        self._derived_spaces._repr = '_derived_spaces'
        self._static_spaces = ImplChainMap([self._self_spaces,
                                                self._derived_spaces])
        self._static_spaces._repr = '_static_spaces'

        self._spaces = ImplChainMap([self._static_spaces,
                                     self._dynamic_spaces])
        self._spaces._repr = '_spaces'

        self._derived_refs = DerivedMembers(self, member='refs')
        self._global_refs = {'__builtins__': __builtins__,
                               'get_self': self.get_self_interface}

        self._refs = LazyEvalChainMap([self._global_refs,
                                       self._arguments,
                                       self._self_refs,
                                       self._derived_refs])
        self._refs._repr = '_refs'

        derived = [self._derived_cells,
                   self._derived_spaces,
                   self._derived_refs]

        for observer in derived:
            self._self_members.append_observer(observer)

        self._namespace_impl = LazyEvalChainMap([self._cells,
                                                 self._spaces,
                                                 self._refs])

        self._namespace = NameSpaceDict(self)
        self._namespace_impl.append_observer(self._namespace)

    # ----------------------------------------------------------------------
    # Serialization by pickle

    state_attrs = [
        'direct_bases',
        'mro',
        '_self_cells',
        '_derived_cells',
        '_cells',
        '_self_spaces',
        '_derived_spaces',
        '_static_spaces',
        '_dynamic_spaces',
        '_global_refs',
        '_arguments',
        '_self_refs',
        '_derived_refs',
        '_refs',
        '_self_members',
        '_observed_bases',
        '_namespace_impl',
        '_namespace',
        'cellsnamer',
        'name',
        'parent'] + SpaceContainerImpl.state_attrs

    def __getstate__(self):
        state = {key: value for key, value in self.__dict__.items()
                 if key in self.state_attrs}

        state['_global_refs'].clear()
        if '__builtins__' in state['_namespace']:
            state['_namespace']['__builtins__'] = '__builtins__'

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._global_refs.update({'__builtins__': __builtins__,
                                    'get_self': self.get_self_interface})
        if '__builtins__' in state['_namespace']:
            state['_namespace']['__builtins__'] = __builtins__

    def restore_state(self, system):
        """Called after unpickling to restore some attributes manually."""

        self.system = system

        for space in self._spaces.values():
            space.restore_state(system)

        for cells in self._cells.values():
            cells.restore_state(system)

    def __repr__(self):
        return '<SpaceImpl: ' + self.name + '>'

    def get_self_interface(self):
        return self.interface

    def get_object(self, name):
        """Retrieve an object by a dotted name relative to the space."""

        parts = name.split('.')
        child = parts.pop(0)

        if parts:
            return self.spaces[child].get_object('.'.join(parts))
        else:
            return self._namespace_impl[child]

    @property
    def repr_(self):

        format_ = dedent("""\
        name: %s
        cells: %s
        spaces: %s
        refs: %s
        """)

        return format_ % (
            self.name,
            list(self.cells.keys()),
            list(self.spaces.keys()),
            list(self.refs.keys())
        )

    # ----------------------------------------------------------------------
    # Components and namespace

    @property
    def self_cells(self):
        return self._self_cells.update_data()

    @property
    def self_spaces(self):
        return self._self_spaces.update_data()

    @property
    def self_refs(self):
        return self._self_refs.update_data()

    @property
    def self_members(self):
        return self._self_members.update_data()

    @property
    def cells(self):
        return self._cells.update_data()

    @property
    def spaces(self):
        return self._spaces.update_data()

    @property
    def refs(self):
        return self._refs.update_data()

    @property
    def namespace_impl(self):
        return self._namespace_impl.update_data()

    @property
    def namespace(self):
        return self._namespace.get_updated_data()

    # ----------------------------------------------------------------------
    # Inheritance

    def _update_mro(self):
        """Calculate the Method Resolution Order of bases using the C3 algorithm.

        Code modified from 
        http://code.activestate.com/recipes/577748-calculate-the-mro-of-a-class/

        Args:
            bases: sequence of direct base spaces.

        """
        seqs = [base.mro.copy() for base
                in self.direct_bases] + [self.direct_bases]
        res = []
        while True:
            non_empty = list(filter(None, seqs))

            if not non_empty:
                # Nothing left to process, we're done.
                self.mro.clear()
                self.mro.extend([self] + res)
                return

            for seq in non_empty:  # Find merge candidates among seq heads.
                candidate = seq[0]
                not_head = [s for s in non_empty if candidate in s[1:]]
                if not_head:
                    # Reject the candidate.
                    candidate = None
                else:
                    break

            if not candidate:
                raise TypeError(
                    "inconsistent hierarchy, no C3 MRO is possible")

            res.append(candidate)

            for seq in non_empty:
                # Remove candidate.
                if seq[0] == candidate:
                    del seq[0]

    # ----------------------------------------------------------------------

    @property
    def model(self):
        return self.parent.model

    def set_cells(self, name, cells):
        self._self_cells[name] = cells
        self._self_cells.set_update(skip_self=True)

    def set_space(self, name, space):
        pass

    def set_name(self, name, value):

        if not is_valid_name(name):
            raise ValueError

        if name in self.namespace:
            if name in self.refs:
                self.refs[name] = value
                self.refs.set_update(skip_self=False)

            elif name in self.cells:
                if self.cells[name].has_single_value():
                    self.cells[name].set_value((), value)
                else:
                    raise AttributeError("Cells '%s' is not a scalar." % name)

            else:
                raise ValueError

        else:
            self._self_refs[name] = value
            self._self_refs.set_update(skip_self=True)

    def remove_cells(self, name):

        if name in self._self_cells:
            self._self_cells[name].parent = None
            del self._self_cells[name]

        for base in self.direct_bases:
            if name in base.cells:
                base_cells = base.cells[name]
                self._derived_cells[name] = \
                    self.new_cells(name=name, func=base_cells.formula)
            break

    def remove_derived(self, name):

        if name in self.namespace:

            if name in self._derived_cells:
                self._derived_cells[name].parent = None
                del self._derived_cells[name]

            elif name in self._derived_spaces:
                self._derived_spaces[name].parent = None
                del self._derived_spaces[name]

            elif name in self._derived_refs:
                del self._derived_refs[name]

            else:
                raise RuntimeError("Name already assigned.")

            return True

        else:
            return False

    def revert_derived(self, name):
        raise NotImplementedError

    def has_bases(self):
        return len(self.mro) > 1

    def is_dynamic(self):
        return bool(self._arguments)

    def new_cells(self, name=None, func=None):
        cells = CellsImpl(space=self, name=name, func=func)
        self.set_cells(cells.name, cells)
        return cells

    def new_cells_from_module(self, module_):
        # Outside formulas only

        module_ = get_module(module_)
        newcells = {}

        for name in dir(module_):
            func = getattr(module_, name)
            if isinstance(func, FunctionType):
                # Choose only the functions defined in the module.
                if func.__module__ == module_.__name__:
                    newcells[name] = \
                        self.new_cells(name, func)

        return newcells

    def new_cells_from_excel(self, book, range_, sheet=None,
                                names_row=None, param_cols=None,
                                param_order=None,
                                transpose=False,
                                names_col=None, param_rows=None):
        """Create multiple cells from an Excel range.

        Args:
            book (str): Path to an Excel file.
            range_ (str): Range expression, such as "A1", "$G4:$K10",
                or named range "NamedRange1".
            sheet (str): Sheet name (case ignored).
            names_row: Cells names in a sequence, or an integer number, or
              a string expression indicating row (or column depending on
              ```orientation```) to read cells names from.
            param_cols: a sequence of them
                indicating parameter columns (or rows depending on ```
                orientation```)
            param_order: a sequence of integers representing
                the order of params and extra_params.
            transpose: in which direction 'vertical' or 'horizontal'
            names_col: a string or a list of names of the extra params.
            param_rows: integer or string expression, or a sequence of them
                indicating row (or column) to be interpreted as parameters.
        """
        import modelx.io.excel as xl

        cellstable = xl.CellsTable(book, range_, sheet,
                                   names_row, param_cols, param_order,
                                   transpose, names_col, param_rows)

        if cellstable.param_names:
            sig = "=None, ".join(cellstable.param_names) + "=None"
        else:
            sig = ""

        blank_func = "def _blank_func(" + sig + "): pass"

        for cellsdata in cellstable.items():
            cells = self.new_cells(name=cellsdata.name, func=blank_func)
            for args, value in cellsdata.items():
                cells.set_value(args, value)

    @property
    def signature(self):
        return self.paramfunc.signature

    def get_fullname(self, omit_model=False):

        fullname = self.name
        parent = self.parent
        while True:
            fullname = parent.name + '.' + fullname
            if hasattr(parent, 'parent'):
                parent = parent.parent
            else:
                if omit_model:
                    separated = fullname.split('.')
                    separated.pop(0)
                    fullname = '.'.join(separated)

                return fullname

    def to_frame(self):

        from modelx.io.pandas import space_to_dataframe

        return space_to_dataframe(self)


class Space(SpaceContainer):
    """Container for cells and other objects referred in formulas.

    Space objects have quite a few mapping members. Those are
    MappyingProxyTypes objects, which are essentially frozen dictionaries.

    ``namespace`` stores all names, with their associated objects,
    that can be referenced in the form of attribute access to the space.
    Those names can also be referenced from within the formulas of the
    cells contained in the space.

    ``namespace`` is broken down into ``cells``, ``spaces`` and ``refs`` maps.
    ``cells`` is a map of all the cells contained in the space,
    and ``spaces`` is a map of all the subspaces of the space.
    ``refs`` contains names and their associated objects that are not
    part of the space but are accessible from the space.

    ``cells`` is further broken down into ``self_cells`` and ``derived_cells``.
    ``self_cells`` contains cells that are newly defined or overridden
    in the class. On the other hand, ``derived_cells`` contains cells
    derived from the space's base class(s).

    ``space`` is first broken down into ``static_spaces`` and
    ``dynamic_spaces``. ``static_spaces`` contains subspaces of the space
    that are explicitly created by the user by the space's ``new_space``
    method or one of its variants. ``dynamic_spaces`` contains parametrized
    subspaces that are created dynamically by ``()`` or ``[]`` operation on
    the space.

    Objects with their associated names are::

        namespace
            cells
                self_cells
                derived_cells
            spaces
                static_spaces
                    self_spaces
                    derived_spaces
                dynamic_spaces
            refs
                self_refs
                derived_refs
                global_refs
                arguments
    """
    # __slots__ = ('_impl',)

    @property
    def name(self):
        """The name of the space."""
        return self._impl.name

    # def __repr__(self):
    #     return self._impl.repr_

    # ----------------------------------------------------------------------
    # Manipulating cells

    def new_cells(self, name=None, func=None):
        """Create a cells in the space.

        Args:
            name: If omitted, the model is named automatically ``CellsN``,
                where ``N`` is an available number.
            func: The function to define the formula of the cells.

        Returns:
            The new cells.
        """
        # Outside formulas only
        return self._impl.new_cells(name, func).interface

    @property
    def cells(self):
        """A mapping of cells names to the cells objects in the space."""
        return self._impl.cells.interfaces

    @property
    def self_cells(self):
        """A mapping that associates names to cells defined in the space"""
        return self._impl.self_cells.interfaces

    @property
    def derived_cells(self):
        """A mapping associating names to derived cells."""
        return self._impl.derived_cells.interfaces

    @property
    def refs(self):
        """A map associating names to objects accessible by the names."""
        return self._impl

    def new_cells_from_module(self, module_):
        """Create a cells from a module."""
        # Outside formulas only

        newcells = self._impl.new_cells_from_module(module_)
        return get_interfaces(newcells)

    def new_cells_from_excel(self, book, range_, sheet=None,
                                names_row=None, param_cols=None,
                                param_order=None,
                                transpose=False,
                                names_col=None, param_rows=None):
        """Create multiple cells from an Excel range.

        To use this method, ``openpyxl`` package must be installed.

        Args:
            book (str): Path to an Excel file.
            range_ (str): Range expression, such as "A1", "$G4:$K10",
                or named range "NamedRange1".
            sheet (str): Sheet name (case ignored).
            names_row (optional): an index number indicating
                what row contains the names of cells and parameters.
                Defaults to the top row (0).
            param_cols (optional): a sequence of index numbers
                indicating parameter columns.
                Defaults to only the leftmost column ([0]).
            names_col (optional): an index number, starting from 0,
                indicating what column contains additional parameters.
            param_rows (optional): a sequence of index numbers, starting from
                0, indicating rows of additional parameters, in case cells are
                defined in two dimensions.
            transpose (optional): Defaults to ``False``.
                If set to ``True``, "row(s)" and "col(s)" in the parameter
                names are interpreted inversely, i.e.
                all indexes passed to "row(s)" parameters are interpreted
                as column indexes,
                and all indexes passed to "col(s)" parameters as row indexes.
            param_order (optional): a sequence to reorder the parameters.
                The elements of the sequence are the indexes of ``param_cols``
                elements, and optionally the index of ``param_rows`` elements
                shifted by the length of ``param_cols``.

        Returns:
            The new cells created from the Excel range.
        """
        return self._impl.new_cells_from_excel(
            book, range_, sheet, names_row, param_cols,
            param_order, transpose,
            names_col, param_rows)

    # ----------------------------------------------------------------------
    # Checking containing subspaces and cells

    def __contains__(self, item):
        """Check if item is in the space.

        item can be wither a cells or space.

        Args:
            item: a cells or space to check.

        Returns:
            True if item is a direct child of the space, False otherwise.
        """

        if isinstance(item, Cells):
            return item in self._cells.values()

        elif isinstance(item, Space):
            return item in self._subspaces.values()

    # ----------------------------------------------------------------------
    # Getting and setting attributes

    def __getattr__(self, name):
        return self._impl.namespace[name]

    def __setattr__(self, name, value):
        self._impl.set_name(name, value)

    # ----------------------------------------------------------------------
    # Manipulating subspaces

    def has_params(self):
        """Check if the parameter function is set."""
        # Outside formulas only
        return bool(self.signature)

    def __getitem__(self, args):
        return self._impl.get_space(args).interface

    def __call__(self, *args, **kwargs):
        return self._impl.get_space(args, kwargs).interface

    def set_paramfunc(self, paramfunc):
        """Set if the parameter function."""
        self._impl.set_paramfunc(paramfunc)

    # ----------------------------------------------------------------------
    # Conversion to Pandas objects

    def to_frame(self):
        """Convert the space itself into a Pandas DataFrame object."""
        return self._impl.to_frame()

    @property
    def frame(self):
        """Alias of ``to_frame()``."""
        return self._impl.to_frame()


