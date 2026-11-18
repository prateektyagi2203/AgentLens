"use client";

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/cn";

interface Props<T> {
  data: T[];
  columns: ColumnDef<T>[];
  caption: string;
  getRowId?: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  initialSort?: SortingState;
  rowClassName?: (row: T) => string | undefined;
  selectedId?: string | null;
  className?: string;
}

/** Keyboard-navigable: rows are focusable when clickable (Enter/Space activates, arrows move), headers sort. */
export function DataTable<T>({ data, columns, caption, getRowId, onRowClick, initialSort, rowClassName, selectedId, className }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });

  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onRowClick?.(row);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const sib = e.key === "ArrowDown" ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling;
      (sib as HTMLElement | null)?.focus();
    }
  };

  return (
    <div className={cn("overflow-x-auto rounded-lg border border-border bg-card", className)}>
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-border">
              {hg.headers.map((h) => {
                const sorted = h.column.getIsSorted();
                const canSort = h.column.getCanSort();
                return (
                  <th key={h.id} scope="col" aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"} className="whitespace-nowrap px-4 py-3 text-left font-mono text-xs font-medium uppercase tracking-widest text-muted-foreground">
                    {h.isPlaceholder ? null : canSort ? (
                      <button type="button" onClick={h.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 uppercase tracking-widest hover:text-foreground">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <span aria-hidden>{sorted === "asc" ? "↑" : sorted === "desc" ? "↓" : ""}</span>
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              tabIndex={onRowClick ? 0 : undefined}
              aria-selected={selectedId ? selectedId === row.id : undefined}
              onClick={onRowClick ? () => onRowClick(row.original) : undefined}
              onKeyDown={onRowClick ? (e) => onKey(e, row.original) : undefined}
              className={cn("border-b border-border last:border-0", onRowClick && "cursor-pointer hover:bg-accent focus-visible:bg-accent", selectedId === row.id && "bg-accent", rowClassName?.(row.original))}
            >
              {row.getVisibleCells().map((c) => (
                <td key={c.id} className="px-4 py-3 align-middle">
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
