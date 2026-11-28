# HTTP contracts for a reading catalogue

## PUT and replacement

PUT requests that a representation replace the state at a client-selected target URI. Applying the same PUT twice has the same intended effect on that resource as applying it once. This property is called idempotency. Suppose a catalogue client writes a complete reading list to a known shelf, loses the reply and repeats the write. The resulting list still contains exactly the items in the submitted representation.

The server may log both attempts. The first response might announce creation and the second report a successful replacement. Idempotency describes the requested effect on the resource, so it does not require identical response codes or identical logs. A client concerned about overwriting a concurrent change can also send a precondition with its write.

## POST and creation

POST asks the target to process the submitted representation according to its own contract. A common collection endpoint allocates a fresh identifier for each new reading list. Repeating that POST can create a second resource. An ordinary creation request has no idempotency guarantee. A timeout after sending the request therefore leaves the client uncertain about what was already created.

A service can define an idempotency key for this operation. It associates the key with the first accepted request and records the outcome. A retry with the same key and equivalent payload can then recover that outcome. The service must define how long it retains the association and how it handles a reused key with a different payload.

## PATCH and partial changes

PATCH applies a change document to the current state. The meaning of each instruction determines the effect of repetition. Setting a shelf's display name to a specified string twice leaves the same display name. Appending a reading to the end of its list twice can add two entries. A client needs the patch format's semantics before deciding whether a retry is safe.

Use a precondition when the change was prepared against a particular version. If the version changed while the editor was working, fetch the current representation and decide which changes still apply. A failed If-Match precondition receives 412 Precondition Failed. This differs from a request whose preconditions passed but whose proposed transition is disallowed by the current resource state.

## DELETE and repeated requests

DELETE asks the service to remove the association between the target URI and its current resource. A repeated DELETE is idempotent in its intended effect. A first attempt may succeed with 204 and a later attempt may find the resource absent and return 404. A reader deciding whether to retry should reason from the final state described by the contract.

Removal from the current catalogue does not by itself promise erasure of every historical record. The service may retain an audit entry for each request. Document separately when the resource disappears from a list and whether an already issued asynchronous removal can still be in progress. Otherwise a successful acceptance message can be mistaken for completion.

## Creation and deferred work

Use 201 Created when the request has created a resource. A Location header can identify the newly created reading list. In contrast, 202 Accepted says that processing was accepted and may finish later. An import that is still waiting in a queue can return a status resource where the client can follow its progress. Acceptance alone does not establish that any readings have been imported.

A useful contract describes a terminal success and a terminal failure for such a job. A client that polls should stop on both. Otherwise it may continue requesting a job that already failed because its input was inconsistent. Store a stable job identifier so a page reload can recover the same progress view.

## State conflicts and temporary failures

A request that conflicts with the resource's current state can receive 409 Conflict. Imagine an editor trying to add a chapter to an edition that was just archived. The proposed state transition is no longer allowed. Report which state prevented the operation so the editor can revise the request. Repeating the identical transition immediately is unlikely to resolve it.

Rate limiting for a particular client can produce 429 Too Many Requests. Temporary service unavailability, such as a saturated import service, can produce 503 Service Unavailable. Either response can carry Retry-After when the service can suggest a delay. Distinguishing these outcomes helps a client decide whether to wait, slow its own traffic or reconcile a change to data.

## Validators and freshness

An ETag is an opaque validator for a selected representation. A client revalidating a cached copy sends its saved ETag in If-None-Match on a conditional GET. If the representation still matches, 304 Not Modified tells the client to reuse its cached body. No representation body is transferred in the 304 response. A changed representation can be returned with a new validator and a new body.

Cache-Control describes storage and reuse. A fresh copy under max-age can satisfy a request locally. With no-cache the stored response has to be validated before reuse. With no-store a cache must avoid storing the response. A client should also use the right variant, for example the edition in the requested language, when selecting the saved validator.

## Browser credentials and CSRF

An HttpOnly cookie keeps its value out of ordinary page scripts, but the browser can still attach it to a request. A cookie-authenticated write therefore needs a CSRF defense. In a signed double-submit scheme, check that the submitted header matches the CSRF cookie and verify the token's binding to the session. The authentication cookie can stay HttpOnly while the client obtains the separate CSRF value for the header.

A Bearer token explicitly placed in the Authorization header is not automatically attached by the browser to a cross-site form submission. An application using that arrangement must still protect the token against disclosure. Treat the way a credential travels as part of the contract. Merely changing the credential's name does not change when the browser sends it.

## Pagination and error contracts

Choose a stable order for reading lists before offering pagination. Add a unique tie breaker when many lists have the same publication date. A cursor can encode the position after the last visible item under that order. Carry the same filter on later requests. If the filter changes, start a new sequence so that the cursor and the visible collection describe the same ordering.

Give errors a stable machine-readable code alongside a short explanation. Clients can translate the explanation or highlight a field without parsing a sentence for clues. For a failed import include an identifier the client can match to the pending operation. Return only the details needed to act on the failure. An internal log entry and a public response serve different readers.
