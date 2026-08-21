/* eslint-disable @typescript-eslint/no-explicit-any */
declare module '*.tsx' {
  const component: React.ComponentType<Record<string, unknown>>;
  export default component;
}

declare module '*.jsx' {
  const component: React.ComponentType<Record<string, unknown>>;
  export default component;
}

declare module '*.css' {
  const content: Record<string, string>;
  export default content;
}

// Webpack require.context type declarations
interface RequireContext {
  keys(): string[];
  (id: string): any;
  <T>(id: string): T;
  resolve(id: string): string;
  id: string;
  // Interface has members, so no-empty-object-type error is resolved
}

declare namespace NodeJS {
  interface Require {
    context(
      directory: string,
      useSubdirectories: boolean,
      regExp: RegExp
    ): RequireContext;
  }
}
