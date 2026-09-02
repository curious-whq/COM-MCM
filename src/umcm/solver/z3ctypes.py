"""Small SMT-LIB backend using the system libz3 through ctypes.

No Python z3 package is required.  The backend solves the pure event/field
constraints with Z3, checks persistent operational state with the same
state checker used by the finite backend, and blocks rejected concrete event
assignments until a state-feasible witness is found.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from pathlib import Path
from typing import Any

from umcm.errors import SolverError
from umcm.ir.expression import (
    Binary, Call, EventField, Expr, Ite, Literal, Nary, Symbol, Unary, iter_literals
)
from umcm.ir.sort import Sort
from umcm.solver.finite import FiniteStatus, _build_variables
from umcm.solver.problem import BoundedProblem
from umcm.solver.state import StateCheckResult, check_state_semantics


@dataclass(slots=True)
class Z3SolveResult:
    status: FiniteStatus
    assignment: dict[str, Any]
    explored_nodes: int
    reason: str = ""
    state_result: StateCheckResult | None = None


class _Codec:
    def __init__(self, problem: BoundedProblem):
        self.problem = problem
        self.variables = _build_variables(problem)
        self.var_map = {v.name: v for v in self.variables}
        self.enum_encode: dict[Sort, dict[Any, int]] = {}
        self.enum_decode: dict[Sort, dict[int, Any]] = {}
        enum_values: dict[Sort, set[Any]] = {}

        def record(sort: Sort, value: Any) -> None:
            if sort.is_bool or sort.is_int or sort.is_bitvector:
                return
            enum_values.setdefault(sort, set()).add(value)

        def record_expr(expr: Expr) -> None:
            for literal in iter_literals(expr):
                record(literal.sort, literal.value)

        # Symbol domains already include concrete values discovered by the finite
        # variable builder.  Also collect concrete event/state literals directly:
        # a model can compare two fully concrete EventField values without ever
        # creating a Symbol of that sort, and those values still need SMT codes.
        for variable in self.variables:
            for value in variable.domain:
                record(variable.sort, value)

        for event in problem.events:
            event_type = problem.catalog.resolve(event.event_type)
            if isinstance(event.occurs, Expr):
                record_expr(event.occurs)
            if isinstance(event.cycle, Expr):
                record_expr(event.cycle)
            for name, value in event.fields.items():
                field_sort = event_type.field_map[name].sort
                if isinstance(value, Expr):
                    record_expr(value)
                else:
                    record(field_sort, value)

        for constraint in problem.constraints:
            record_expr(constraint.expression)
        for state_variable in problem.spec.state_variables:
            if isinstance(state_variable.initial, Expr):
                record_expr(state_variable.initial)
            else:
                record(state_variable.sort, state_variable.initial)
        for requirement in problem.state_requirements:
            record_expr(requirement.activation)
            record_expr(requirement.cycle)
            record_expr(requirement.expected)
        for update in problem.state_updates:
            record_expr(update.activation)
            record_expr(update.cycle)
            record_expr(update.value)
        for forward in problem.guarded_forwards:
            record_expr(forward.antecedent)
            record_expr(forward.consequent)
            for predicate in forward.predicates:
                record_expr(predicate.cycle)
                record_expr(predicate.expected)
        for support in problem.guarded_supports:
            record_expr(support.antecedent)
            for candidate in support.supports:
                record_expr(candidate.expression)
                for predicate in candidate.predicates:
                    record_expr(predicate.cycle)
                    record_expr(predicate.expected)

        for sort, values in enum_values.items():
            ordered = sorted(values, key=lambda value: (type(value).__name__, repr(value)))
            encoding = {value: index for index, value in enumerate(ordered)}
            self.enum_encode[sort] = encoding
            self.enum_decode[sort] = {index: value for value, index in encoding.items()}
        self.events=problem.event_map

    @staticmethod
    def q(name:str)->str:
        return '|' + name.replace('\\','\\\\').replace('|','\\|') + '|'

    def sort_smt(self, sort:Sort)->str:
        if sort.is_bool: return 'Bool'
        if sort.is_bitvector: return f'(_ BitVec {sort.width})'
        return 'Int'

    @staticmethod
    def int_atom(v:int)->str:
        return str(v) if v>=0 else f'(- {-v})'

    def literal(self, sort:Sort, value:Any)->str:
        if sort.is_bool: return 'true' if value else 'false'
        if sort.is_int: return self.int_atom(int(value))
        if sort.is_bitvector:
            return f'(_ bv{int(value)} {sort.width})'
        try: code=self.enum_encode[sort][value]
        except KeyError as exc: raise SolverError(f'no SMT enum code for {value!r} in {sort}') from exc
        return str(code)

    def expr(self, x:Expr)->str:
        if isinstance(x,Literal): return self.literal(x.sort,x.value)
        if isinstance(x,Symbol): return self.q(x.name)
        if isinstance(x,EventField):
            ev=self.events[x.event_id]
            if x.field=='occurs': val=ev.occurs
            elif x.field=='cycle': val=ev.cycle
            else: val=ev.fields.get(x.field)
            if val is None: raise SolverError(f'missing event field {x.event_id}.{x.field}')
            if isinstance(val,Expr): return self.expr(val)
            return self.literal(x.sort,val)
        if isinstance(x,Unary):
            a=self.expr(x.operand)
            return f'(not {a})' if x.op=='not' else f'(- {a})'
        if isinstance(x,Binary):
            a,b=self.expr(x.left),self.expr(x.right)
            op={'and':'and','or':'or','implies':'=>','xor':'xor','eq':'=','ne':'distinct','lt':'<','le':'<=','gt':'>','ge':'>=','add':'+','sub':'-','mul':'*','div':'div','mod':'mod'}[x.op]
            return f'({op} {a} {b})'
        if isinstance(x,Nary):
            args=' '.join(self.expr(i) for i in x.operands)
            op={'and':'and','or':'or','distinct':'distinct'}[x.op]
            return f'({op} {args})' if x.operands else ('true' if x.op=='and' else 'false')
        if isinstance(x,Ite): return f'(ite {self.expr(x.condition)} {self.expr(x.then_expr)} {self.expr(x.else_expr)})'
        if isinstance(x,Call):
            args=[self.expr(i) for i in x.arguments]
            if x.function in {'same_address','same_identity','same_op','same_value'}:
                if len(args)<=1:return 'true'
                return f'(= {" ".join(args)})'
            if x.function=='same_block':
                # Current µMCM address tokens identify abstract cache-line locations.
                return f'(= {args[0]} {args[1]})'
            if x.function=='mask_overlap': return f'(not (= (bvand {args[0]} {args[1]}) (_ bv0 8)))'
            if x.function=='mask_covers': return f'(= (bvand {args[0]} {args[1]}) {args[1]})'
            raise SolverError(f'unsupported SMT call {x.function}')
        raise SolverError(f'unsupported SMT expression {type(x).__name__}')

    def declaration(self,v)->str:
        return f'(declare-const {self.q(v.name)} {self.sort_smt(v.sort)})'

    def domain_assertion(self,v)->str|None:
        vals=[self.literal(v.sort,x) for x in v.domain]
        if v.sort.is_bool: return None
        if not vals: return None
        q=self.q(v.name)
        if len(vals)==1:return f'(assert (= {q} {vals[0]}))'
        return f'(assert (or {" ".join(f"(= {q} {x})" for x in vals)}))'

    def decode_atom(self, sort:Sort, sexpr:Any)->Any:
        if sort.is_bool:
            if sexpr=='true':return True
            if sexpr=='false':return False
        if sort.is_bitvector:
            if isinstance(sexpr,str) and sexpr.startswith('#x'): return int(sexpr[2:],16)
            if isinstance(sexpr,str) and sexpr.startswith('#b'): return int(sexpr[2:],2)
            if isinstance(sexpr,list) and len(sexpr)>=2 and sexpr[0]=='_' and str(sexpr[1]).startswith('bv'): return int(str(sexpr[1])[2:])
        if isinstance(sexpr,list) and len(sexpr)==2 and sexpr[0]=='-': num=-int(sexpr[1])
        else: num=int(sexpr)
        if sort.is_int:return num
        if sort.is_bitvector:return num
        try:return self.enum_decode[sort][num]
        except KeyError as exc: raise SolverError(f'bad SMT enum {num} for {sort}') from exc


def _libz3():
    candidates=['/lib/x86_64-linux-gnu/libz3.so.4','libz3.so.4','libz3.so']
    last=None
    for path in candidates:
        try: lib=ctypes.CDLL(path); break
        except OSError as e:last=e
    else: raise SolverError(f'libz3 unavailable: {last}')
    lib.Z3_mk_config.restype=ctypes.c_void_p
    lib.Z3_mk_context_rc.argtypes=[ctypes.c_void_p]; lib.Z3_mk_context_rc.restype=ctypes.c_void_p
    lib.Z3_del_config.argtypes=[ctypes.c_void_p]
    lib.Z3_del_context.argtypes=[ctypes.c_void_p]
    lib.Z3_eval_smtlib2_string.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; lib.Z3_eval_smtlib2_string.restype=ctypes.c_char_p
    return lib


def _eval_smt(script:str)->str:
    lib=_libz3(); cfg=lib.Z3_mk_config(); ctx=lib.Z3_mk_context_rc(cfg); lib.Z3_del_config(cfg)
    try:
        out=lib.Z3_eval_smtlib2_string(ctx,script.encode())
        if not out: raise SolverError('libz3 returned null output')
        return out.decode()
    finally: lib.Z3_del_context(ctx)


def _tokenize(s:str):
    out=[]; i=0
    while i<len(s):
        c=s[i]
        if c.isspace(): i+=1; continue
        if c in '()': out.append(c); i+=1; continue
        if c=='|':
            j=i+1; buf=[]
            while j<len(s) and s[j]!='|':
                if s[j]=='\\' and j+1<len(s): j+=1
                buf.append(s[j]); j+=1
            out.append(''.join(buf)); i=j+1; continue
        j=i
        while j<len(s) and not s[j].isspace() and s[j] not in '()': j+=1
        out.append(s[i:j]); i=j
    return out


def _parse_sexprs(s:str):
    toks=_tokenize(s); pos=0; forms=[]
    def one():
        nonlocal pos
        if toks[pos]=='(':
            pos+=1; arr=[]
            while toks[pos]!=')': arr.append(one())
            pos+=1; return arr
        x=toks[pos]; pos+=1; return x
    while pos<len(toks): forms.append(one())
    return forms


def _assignment_from_output(output:str, codec:_Codec)->tuple[str,dict[str,Any]]:
    lines=output.strip().splitlines()
    if not lines:return 'unknown',{}
    status=lines[0].strip()
    if status!='sat': return status,{}
    forms=_parse_sexprs('\n'.join(lines[1:]))
    pairs=forms[0] if forms else []
    result={}
    for item in pairs:
        if not isinstance(item,list) or len(item)!=2: continue
        name=item[0]; value=item[1]
        if name not in codec.var_map: continue
        result[name]=codec.decode_atom(codec.var_map[name].sort,value)
    return status,result




def _state_symbol(codec: _Codec, state_name: str, cycle: int) -> str:
    return codec.q(f"__state__::{state_name}::pre::{cycle}")


def _state_compare_smt(op: str, actual: str, expected: str) -> str:
    smt_op = {
        "eq": "=",
        "ne": "distinct",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
    }[op]
    return f"({smt_op} {actual} {expected})"


def _state_predicate_smt(codec: _Codec, problem: BoundedProblem, predicate) -> str:
    """Encode a pre-state predicate whose anchor cycle is symbolic."""
    cycle_expr = codec.expr(predicate.cycle)
    expected = codec.expr(predicate.expected)
    cases = []
    for cycle in range(problem.spec.horizon + 1):
        actual = _state_symbol(codec, predicate.state, cycle)
        holds = _state_compare_smt(predicate.op, actual, expected)
        cases.append(f"(and (= {cycle_expr} {cycle}) {holds})")
    return "(or " + " ".join(cases) + ")" if cases else "false"


def _state_smt_constraints(codec: _Codec, problem: BoundedProblem) -> list[str]:
    """Compile persistent operational state into ordinary SMT constraints.

    State at ``pre[c]`` is the value visible to guards/requirements in cycle c.
    Active updates in cycle c are atomic and determine ``pre[c+1]``; when no
    update is active the cell stutters.  Pairwise-active writes must agree.
    This mirrors ``check_state_semantics`` and prevents Z3 from enumerating a
    large number of event-only models that are later rejected by the state
    checker.
    """
    if not problem.spec.state_variables:
        return []

    lines: list[str] = []
    state_map = {item.name: item for item in problem.spec.state_variables}
    horizon = problem.spec.horizon

    # Declare pre-state snapshots 0..horizon+1.  The final snapshot is useful
    # for validating updates that happen at the last bounded cycle.
    for variable in problem.spec.state_variables:
        for cycle in range(horizon + 2):
            lines.append(
                f"(declare-const {_state_symbol(codec, variable.name, cycle)} "
                f"{codec.sort_smt(variable.sort)})"
            )
        initial = (
            codec.expr(variable.initial)
            if isinstance(variable.initial, Expr)
            else codec.literal(variable.sort, variable.initial)
        )
        lines.append(
            f"(assert (= {_state_symbol(codec, variable.name, 0)} {initial}))"
        )

    # Ordinary requirements observe the shared pre-state at their anchor cycle.
    for requirement in problem.state_requirements:
        activation = codec.expr(requirement.activation)
        cycle_expr = codec.expr(requirement.cycle)
        expected = codec.expr(requirement.expected)
        for cycle in range(horizon + 1):
            actual = _state_symbol(codec, requirement.state, cycle)
            holds = _state_compare_smt(requirement.op, actual, expected)
            lines.append(
                f"(assert (=> (and {activation} (= {cycle_expr} {cycle})) {holds}))"
            )

    # State-guarded transformations use the same pre-state semantics, but a
    # false state guard disables the transformation instead of invalidating the
    # trace.
    for forward in problem.guarded_forwards:
        antecedent = codec.expr(forward.antecedent)
        guards = [
            _state_predicate_smt(codec, problem, predicate)
            for predicate in forward.predicates
        ]
        enabled = "(and " + " ".join([antecedent, *guards]) + ")" if guards else antecedent
        lines.append(
            f"(assert (=> {enabled} {codec.expr(forward.consequent)}))"
        )

    for support in problem.guarded_supports:
        antecedent = codec.expr(support.antecedent)
        candidates = []
        for candidate in support.supports:
            pieces = [codec.expr(candidate.expression)]
            pieces.extend(
                _state_predicate_smt(codec, problem, predicate)
                for predicate in candidate.predicates
            )
            candidates.append(
                pieces[0] if len(pieces) == 1 else "(and " + " ".join(pieces) + ")"
            )
        rhs = "false" if not candidates else (
            candidates[0] if len(candidates) == 1 else "(or " + " ".join(candidates) + ")"
        )
        lines.append(f"(assert (=> {antecedent} {rhs}))")

    # Atomic updates and stuttering transitions.
    updates_by_state = {name: [] for name in state_map}
    for update in problem.state_updates:
        updates_by_state[update.state].append(update)

    for state_name, variable in state_map.items():
        updates = updates_by_state[state_name]
        for cycle in range(horizon + 1):
            active_terms: list[tuple[str, str]] = []
            for update in updates:
                active = (
                    f"(and {codec.expr(update.activation)} "
                    f"(= {codec.expr(update.cycle)} {cycle}))"
                )
                value = codec.expr(update.value)
                active_terms.append((active, value))

            # Simultaneous writes to the same cell must agree.
            for left in range(len(active_terms)):
                for right in range(left + 1, len(active_terms)):
                    a_active, a_value = active_terms[left]
                    b_active, b_value = active_terms[right]
                    lines.append(
                        f"(assert (=> (and {a_active} {b_active}) (= {a_value} {b_value})))"
                    )

            current = _state_symbol(codec, state_name, cycle)
            next_state = _state_symbol(codec, state_name, cycle + 1)
            expression = current
            for active, value in reversed(active_terms):
                expression = f"(ite {active} {value} {expression})"
            lines.append(f"(assert (= {next_state} {expression}))")

    return lines

def _block_clause(codec:_Codec, assignment:dict[str,Any])->str:
    terms=[]
    for v in codec.variables:
        if v.name not in assignment: continue
        # Block occurrence decisions and concrete data/timing of events that occur.
        include=True
        if v.name.startswith('slot::') and '::occurs' not in v.name:
            eid=v.name.split('::')[1]
            occ=assignment.get(f'slot::{eid}::occurs')
            include=(occ is True)
        if include:
            terms.append(f'(= {codec.q(v.name)} {codec.literal(v.sort,assignment[v.name])})')
    if not terms:return '(assert false)'
    return f'(assert (not (and {" ".join(terms)})))'


def solve_z3(problem:BoundedProblem, *, max_state_rejections:int=256)->Z3SolveResult:
    codec=_Codec(problem)
    pre=[]
    for v in codec.variables:
        pre.append(codec.declaration(v))
        dom=codec.domain_assertion(v)
        if dom:pre.append(dom)
    for c in problem.constraints: pre.append(f'(assert {codec.expr(c.expression)})')
    pre.extend(_state_smt_constraints(codec, problem))
    blocks=[]
    names=' '.join(codec.q(v.name) for v in codec.variables)
    slot_occurrence_names = [
        f'slot::{event_id}::occurs'
        for event_id in problem.slot_ids
        if f'slot::{event_id}::occurs' in codec.var_map
    ]
    minimize_slots = ''
    if slot_occurrence_names:
        terms = ' '.join(
            f'(ite {codec.q(name)} 1 0)' for name in slot_occurrence_names
        )
        minimize_slots = f'(minimize (+ {terms}))'
    last_reason=''
    for iteration in range(max_state_rejections+1):
        base_parts = [*pre, *blocks]
        if minimize_slots:
            base_parts.append(minimize_slots)
        base = '\n'.join(base_parts)
        # Do not issue get-value after an UNSAT check: the low-level SMT-LIB
        # evaluator treats that as a command error rather than a benign response.
        status_output = _eval_smt(base + '\n(check-sat)')
        status = status_output.strip().splitlines()[0] if status_output.strip() else 'unknown'
        if status=='unsat':
            return Z3SolveResult(FiniteStatus.UNSAT,{},iteration+1,last_reason or 'SMT constraints are unsatisfiable')
        if status!='sat': return Z3SolveResult(FiniteStatus.UNKNOWN,{},iteration+1,f'Z3 returned {status}')
        output = _eval_smt(base + '\n(check-sat)\n' + f'(get-value ({names}))')
        status,assignment=_assignment_from_output(output,codec)
        # Z3 should return all declared values.
        missing=[v.name for v in codec.variables if v.name not in assignment]
        if missing: raise SolverError(f'Z3 model omitted variables: {missing[:5]}')
        state=check_state_semantics(problem,assignment)
        if state.feasible:
            return Z3SolveResult(FiniteStatus.SAT,assignment,iteration+1,state_result=state)
        last_reason=state.reason
        blocks.append(_block_clause(codec,assignment))
    return Z3SolveResult(FiniteStatus.UNKNOWN,{},max_state_rejections+1,f'too many state-rejected SMT candidates; last: {last_reason}')
