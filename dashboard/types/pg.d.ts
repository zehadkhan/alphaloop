/** Fallback types when devDependencies are omitted during install. */
declare module "pg" {
  import { EventEmitter } from "events";

  export interface QueryResult<T = unknown> {
    rows: T[];
    rowCount: number | null;
  }

  export class Pool extends EventEmitter {
    constructor(config?: object);
    query<T = unknown>(text: string, values?: unknown[]): Promise<QueryResult<T>>;
    end(): Promise<void>;
  }
}
