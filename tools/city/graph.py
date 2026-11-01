"""The build graph: nodes are build steps, edges come from files.

A node declares the files it reads (`inputs`), the scripts that implement it (`tools`), its
parameters, and the files it writes (`outputs`), all as path patterns (tools/city/hashing.py).
Node B depends on node A when one of B's inputs overlaps one of A's outputs, plus any
explicit `after` ids. So the graph follows the files, and a new step only has to say what it
reads and writes.

A node's *key* is the hash of: its id and action kind, its parameters, the content of its
tools and the content of its inputs. A node is fresh when its key equals the key recorded
in its stamp (the last successful build) and its outputs on disk are what that build wrote.
"""
import json
from dataclasses import dataclass, field
from typing import Callable

from . import hashing

ACTION_VERSION = 1      # bump to invalidate every stamp


@dataclass
class Node:
    id: str
    kind: str                                   # action kind (tools/city/actions.py)
    inputs: list = field(default_factory=list)   # patterns the step reads
    outputs: list = field(default_factory=list)  # patterns the step writes
    tools: list = field(default_factory=list)    # scripts that implement the step (hashed)
    params: dict = field(default_factory=dict)
    pool: str = "cpu"                           # blender | pigment | godot | cpu (concurrency limits)
    model: str = ""                             # owning smart model ("building/building_a")
    title: str = ""
    after: list = field(default_factory=list)   # explicit extra dependencies (node ids)
    mutable: list = field(default_factory=list)  # outputs other steps may patch: tracked, not verified
    cache: bool = True                          # keep outputs in the content-addressed cache
    always: bool = False                        # gates: run on every build of their target
    run: Callable | None = None                 # filled by the rules (actions)

    def describe(self) -> dict:
        return {"id": self.id, "kind": self.kind, "inputs": self.inputs, "outputs": self.outputs,
                "tools": self.tools, "params": self.params, "pool": self.pool, "model": self.model}


class CycleError(Exception):
    def __init__(self, cycle):
        self.cycle = cycle
        super().__init__("dependency cycle: " + " -> ".join(cycle))


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.deps: dict[str, set] = {}
        self.users: dict[str, set] = {}

    def add(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise ValueError(f"duplicate node {node.id}")
        self.nodes[node.id] = node
        return node

    # ------------------------------------------------------------ edges
    def link(self):
        """Derive edges from overlapping inputs / outputs (and `after`), then check for cycles."""
        self.deps = {n: set() for n in self.nodes}
        self.users = {n: set() for n in self.nodes}
        # index producers by their first two path segments to keep this near-linear
        index = {}
        for a in self.nodes.values():
            for o in a.outputs + a.mutable:
                index.setdefault(_bucket(o), []).append((o, a.id))
        for b in self.nodes.values():
            for i in b.inputs:
                for bk in _buckets_for(i, index):
                    for o, aid in index.get(bk, ()):
                        if aid != b.id and hashing.overlaps(i, o):
                            self.deps[b.id].add(aid)
            for aid in b.after:
                if aid in self.nodes and aid != b.id:
                    self.deps[b.id].add(aid)
        for b, ds in self.deps.items():
            for a in ds:
                self.users[a].add(b)
        self.check_cycles()
        return self

    def check_cycles(self):
        WHITE, GREY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        stack = []
        for root in sorted(self.nodes):
            if color[root] != WHITE:
                continue
            it = [(root, iter(sorted(self.deps[root])))]
            color[root] = GREY
            stack = [root]
            while it:
                n, children = it[-1]
                nxt = next(children, None)
                if nxt is None:
                    color[n] = BLACK
                    it.pop()
                    stack.pop()
                    continue
                if color[nxt] == GREY:
                    cyc = stack[stack.index(nxt):] + [nxt]
                    raise CycleError(list(reversed(cyc)))
                if color[nxt] == WHITE:
                    color[nxt] = GREY
                    stack.append(nxt)
                    it.append((nxt, iter(sorted(self.deps[nxt]))))

    def topo(self, ids=None) -> list[str]:
        ids = set(self.nodes) if ids is None else set(ids)
        indeg = {n: len(self.deps[n] & ids) for n in ids}
        ready = sorted(n for n, d in indeg.items() if d == 0)
        out = []
        while ready:
            n = ready.pop(0)
            out.append(n)
            for u in sorted(self.users[n] & ids):
                indeg[u] -= 1
                if indeg[u] == 0:
                    ready.append(u)
            ready.sort()
        if len(out) != len(ids):
            self.check_cycles()
        return out

    def upstream(self, ids) -> set:
        seen, todo = set(), list(ids)
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            todo.extend(self.deps[n])
        return seen

    def downstream(self, ids) -> set:
        seen, todo = set(), list(ids)
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            todo.extend(self.users[n])
        return seen

    def select(self, targets) -> set:
        """Node ids for target names: a node id, a model ("building/building_a" or "building_a"),
        a kind prefix ("pigment"), or a glob over ids ("world.mesh:*")."""
        import fnmatch
        if not targets:
            return set(self.nodes)
        out = set()
        for t in targets:
            hit = {n for n, nd in self.nodes.items()
                   if n == t or nd.model == t or nd.model.split("/")[-1] == t or n.split(":")[0] == t
                   or fnmatch.fnmatchcase(n, t) or fnmatch.fnmatchcase(nd.model, t)}
            if not hit:
                raise KeyError(f"no node or model matches {t!r}")
            out |= hit
        return out


def _bucket(p: str) -> str:
    segs = hashing._segs(p)
    head = []
    for s in segs[:2]:
        if hashing.has_magic(s):
            break
        head.append(s)
    return "/".join(head)


def _buckets_for(pattern, index):
    """Index buckets an input pattern may overlap."""
    segs = hashing._segs(pattern)
    cands = {""}
    head = []
    for s in segs[:2]:
        if hashing.has_magic(s):
            return list(index)          # wildcard high up: check everything
        head.append(s)
        cands.add("/".join(head))
    # a short input ("assets") also overlaps every longer bucket below it
    if len(segs) < 2:
        cands |= {k for k in index if k.startswith(segs[0] + "/")} if segs else set(index)
    return [c for c in cands if c in index]


# ---------------------------------------------------------------- keys
def node_key(node: Node) -> tuple[str, dict]:
    """(key, detail): the detail records each part's hash so `status` can say what changed."""
    detail = {"params": hashing.sha(node.params), "kind": node.kind, "v": ACTION_VERSION,
              "tools": {}, "inputs": {}}
    for t in node.tools:
        detail["tools"][t] = hashing.pattern_hash(t)[0]
    for i in node.inputs:
        detail["inputs"][i] = hashing.pattern_hash(i)[0]
    key = hashing.sha({"id": node.id, **detail})
    return key, detail


def explain(detail: dict, prev: dict | None) -> list[str]:
    """Why a node is stale, from its current key detail and its last stamp."""
    if not prev:
        return ["never built"]
    pd = prev.get("detail", {})
    why = []
    if str(prev.get("key", "")).startswith("partial:"):
        why.append("last build was a fast partial build (" + (prev.get("note") or "fast path") + ")")
    if pd.get("v") != detail.get("v") or pd.get("kind") != detail.get("kind"):
        why.append("build system changed")
    if pd.get("params") != detail.get("params"):
        why.append("parameters changed")
    for sec, label in (("tools", "tool"), ("inputs", "input")):
        a, b = pd.get(sec, {}), detail.get(sec, {})
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                why.append(f"{label} {'added' if k not in a else 'removed' if k not in b else 'changed'}: {k}")
    return why or ["key changed"]


def dumps_graph(g: Graph) -> str:
    return json.dumps({n: sorted(g.deps[n]) for n in sorted(g.nodes)}, indent=1)
