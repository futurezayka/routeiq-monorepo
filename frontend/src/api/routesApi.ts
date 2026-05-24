import { baseApi } from "./baseApi";
import type { Route, RouteCreate } from "../types";

export const routesApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    listRoutes: build.query<Route[], void>({
      query: () => "/routes",
      providesTags: (result) =>
        result
          ? [
              ...result.map((r) => ({ type: "Route" as const, id: r.id })),
              { type: "Route" as const, id: "LIST" },
            ]
          : [{ type: "Route" as const, id: "LIST" }],
    }),
    planRoute: build.mutation<Route, RouteCreate>({
      query: (body) => ({ url: "/routes", method: "POST", body }),
      invalidatesTags: [{ type: "Route", id: "LIST" }],
    }),
    getRoute: build.query<Route, string>({
      query: (id) => `/routes/${id}`,
      providesTags: (_result, _error, id) => [{ type: "Route", id }],
    }),
  }),
});

export const { useListRoutesQuery, usePlanRouteMutation, useGetRouteQuery } =
  routesApi;
