import Link from "next/link";
import type { ComponentProps } from "react";

/** Next Link with prefetch off so browsing does not generate background requests. */
export default function SLink(props: ComponentProps<typeof Link>) {
  return <Link prefetch={false} {...props} />;
}
