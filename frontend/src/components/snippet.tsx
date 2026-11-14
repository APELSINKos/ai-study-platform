import { Fragment } from "react";

import type { SnippetPart } from "@/lib/api/types";

/**
 * A passage's words in reading order, with the words a query matched marked as if with a
 * highlighter. The parts arrive as plain text and stay plain text: no part is read as markup.
 */
export function Snippet({ parts }: { parts: SnippetPart[] }) {
  return (
    <>
      {parts.map((part, index) =>
        part.highlighted ? (
          <mark key={index}>{part.text}</mark>
        ) : (
          <Fragment key={index}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}
