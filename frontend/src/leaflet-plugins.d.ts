// Ambient typings for Leaflet plugins that ship without their own .d.ts.
// We use only a small slice of each API, so a narrow declaration is enough
// to keep the compiler happy without pulling in @types/* shims.

declare module "leaflet-ant-path" {
  import type { FeatureGroup, LatLngExpression } from "leaflet";

  export interface AntPathOptions {
    color?: string;
    pulseColor?: string;
    weight?: number;
    opacity?: number;
    delay?: number;
    dashArray?: [number, number] | string;
    paused?: boolean;
    reverse?: boolean;
    hardwareAcceleration?: boolean;
  }

  export class AntPath extends FeatureGroup {
    constructor(path: LatLngExpression[], options?: AntPathOptions);
    setLatLngs(latlngs: LatLngExpression[]): this;
    pause(): boolean;
    resume(): boolean;
    reverse(): this;
  }

  export function antPath(
    path: LatLngExpression[] | Array<[number, number]>,
    options?: AntPathOptions,
  ): AntPath;
}

declare module "leaflet-polylinedecorator" {
  // The plugin attaches L.polylineDecorator + L.Symbol on import — we use
  // those globals through (L as unknown as ...) casts at call sites, so the
  // module itself just needs to be import-able.
}
