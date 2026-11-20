---- MODULE Lease ----
EXTENDS Naturals, FiniteSets
CONSTANTS Workers, MaxToken
VARIABLES owner, token, believes, held, stored, prev

Init == /\ owner = "none" /\ token = 0
        /\ believes = [w \in Workers |-> FALSE]
        /\ held = [w \in Workers |-> 0]
        /\ stored = 0 /\ prev = 0

\* 发放租约：令牌严格递增，持有者记住自己拿到的令牌
Acquire(w) == /\ owner = "none" /\ token < MaxToken
              /\ owner' = w /\ token' = token + 1
              /\ believes' = [believes EXCEPT ![w] = TRUE]
              /\ held' = [held EXCEPT ![w] = token + 1]
              /\ UNCHANGED <<stored, prev>>

\* 故障：租约过期，但旧持有者并不知道，仍然自认为持有
Expire == /\ owner # "none" /\ owner' = "none"
          /\ UNCHANGED <<token, believes, held, stored, prev>>

\* 写入：存储端按令牌比较并写入，是一个原子步；旧令牌被拒绝
Write(w) == /\ believes[w]
            /\ prev' = stored
            /\ stored' = IF held[w] >= stored THEN held[w] ELSE stored
            /\ believes' = [believes EXCEPT ![w] = FALSE]
            /\ UNCHANGED <<owner, token, held>>

Next == \/ \E w \in Workers : Acquire(w) \/ Write(w)
        \/ Expire

Bounded == stored <= token
Fenced == stored >= prev
SingleBeliever == Cardinality({w \in Workers : believes[w]}) <= 1
====
