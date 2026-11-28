# Paths, searches and orders in graphs

## Adjacency lists

Let V count vertices and E count edges. An adjacency list gives each vertex a collection of its outgoing neighbors. For a weighted graph, store the destination and weight together in each entry. An isolated vertex still needs a place in the collection of vertices even though its neighbor list is empty. An undirected connection normally appears in both endpoints' lists, so the number of entries grows in proportion to E.

The total space is O(V + E). Enumerating neighbors costs time proportional to the outgoing degree. Checking whether one particular neighbor is present may require scanning that entire list. This representation fits a sparse map where a junction has only a few outgoing roads even though the map contains many junctions.

## Adjacency matrices

Number the vertices and allocate a square table with one row and column for each. Looking up the cell for an ordered pair takes constant time. A full row scan costs O(V), even for a vertex with one neighbor. Storage is O(V squared), independent of how many cells actually describe connections. A dense graph with frequent membership queries can justify that cost.

In a weighted matrix use a separate absence marker if zero is a valid edge weight. Otherwise a free connection disappears when the code tests for a nonzero cell. A symmetric table represents an undirected graph, while asymmetric cells can express one-way travel. A matrix with a single weight per cell also needs a policy for parallel edges.

## Breadth-first search

For a graph with equal edge costs, breadth-first search visits vertices in order of their distance from the start, measured in edges. Maintain a FIFO queue and mark each vertex on discovery. Set its predecessor to the vertex that first discovered it. The queue processes every vertex in one layer before processing vertices in the next. The first discovery therefore gives a shortest unweighted path.

To recover the route, follow predecessors from the target to the start and reverse the sequence. A target never marked has no such route from this start. Marking only when removing a vertex can allow many copies of a shared neighbor into the queue. Marking when adding it avoids those duplicate entries. With lists, scanning a reachable graph takes O(V + E) time in the worst case.

## Depth-first search and cycles

Depth-first search follows an unexplored edge until it must backtrack. An explicit stack can hold both the active vertex and a cursor into its remaining neighbors. This reproduces the return step of a recursive walk and avoids making a long chain depend on the language's call-stack limit. Save a finish event after the last neighbor has been processed.

To detect a directed cycle, distinguish an unseen vertex, a vertex on the active path and a finished vertex. An edge back to an active vertex closes a cycle. An edge to a finished vertex can simply join two branches. In an undirected graph the edge back to the parent also appears in the child's list. Account for that same edge before treating a visited neighbor as evidence of a cycle.

## Dijkstra and a binary heap

Dijkstra's algorithm finds shortest distances from one start when every reachable edge has a non-negative weight. Store tentative distances in a binary min-heap and settle the vertex with the smallest tentative distance. Once it is settled, a route through a later vertex cannot lower its distance. A relaxation improves a neighbor's tentative value when the newly calculated route costs less.

With adjacency lists and a binary heap supporting decrease-key, the worst-case time complexity is O((V + E) log V). The V extractions and up to E successful priority changes pay the logarithmic heap cost. An indexed heap tracks the position of each unsettled vertex. The bound assumes that bookkeeping. A plain heap implementation that inserts duplicate entries instead must discard outdated distances as it pops them.

## Bellman-Ford and repeated relaxation

Bellman-Ford allows negative edges. Initialize the start at zero and every other distance at infinity. Relax every edge on each pass, skipping an edge whose tail is still unreachable. After at most V minus one passes every reachable shortest simple path has been considered. The worst-case time complexity is O(V * E), since each pass examines up to E edges. An unchanged pass permits early termination.

One additional pass tests for a reachable negative cycle. If a distance can still decrease, the route can exploit a cycle with negative total weight. A finite shortest distance then does not exist for vertices reachable from that cycle. A cycle in a disconnected part of the graph cannot affect distances from the chosen start. Checking reachability before adding a weight also avoids arithmetic on the infinity marker.

## Topological sorting

### Kahn's algorithm

For prerequisite edges pointing from an earlier task to a later one, count the incoming edges at every vertex. Put every zero-indegree vertex in a queue. Emit one, remove its outgoing edges by decrementing the corresponding counts, and enqueue any neighbor whose count becomes zero. Every emitted task has already lost all of its outstanding prerequisites.

If the queue empties before all vertices have been emitted, the remaining graph contains a directed cycle. Some remaining vertices may merely depend on that cycle. A branching dependency can produce more than one valid order. Choosing among available vertices by a consistent key makes repeated demonstrations reproducible without implying that the order is unique.

### DFS post-order

A depth-first traversal can order a directed acyclic graph using its finish events. Append each vertex after completing its outgoing neighbors, then reverse the finish order. An edge from an earlier prerequisite to a later task now points forward. Start another traversal at each unseen vertex so disconnected components also appear in the result.

During the traversal, an edge to a vertex on the active path invalidates the ordering because it indicates a cycle. Verify an alleged order by building a position table and checking that every edge points from a lower position to a higher one. This check accepts different valid orders and catches a reversed convention for the direction of prerequisite edges.

## Choosing a path objective

A path with the fewest edges can have a higher total weight than a longer path. Before deciding on a search, write down whether the objective counts steps, sums weights or merely requires feasibility. For example, a timetable can be seen as a set of dependencies even if it has no meaningful cost on an edge. An ordering then answers a different question from a route between two vertices.

Include an unreachable vertex, a zero-cost edge and two equal-cost routes in a small hand-worked example. State how ties are recorded. A predecessor array normally describes one shortest route per reachable destination. Keeping all optimal predecessors answers a different question and can produce many routes even in a small acyclic graph.
