# Bash Effectful Operations

Under `set -e`, a command on the RHS of `&&` is NOT caught by the error trap — bash treats the whole list as "tested." When the RHS has a side effect that an invariant depends on (file write, state append, audit log), use an explicit `if`-block with failure handling instead.
