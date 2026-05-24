import { baseApi } from "./baseApi";
import type { Incident, IncidentCreate } from "../types";

export const incidentsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    listIncidents: build.query<Incident[], void>({
      query: () => "/incidents",
      providesTags: ["Incident"],
    }),
    reportIncident: build.mutation<Incident, IncidentCreate>({
      query: (body) => ({ url: "/incidents", method: "POST", body }),
      invalidatesTags: ["Incident"],
    }),
    resolveIncident: build.mutation<Incident, string>({
      query: (id) => ({ url: `/incidents/${id}/resolve`, method: "PATCH" }),
      invalidatesTags: ["Incident"],
    }),
    resolveStale: build.mutation<{ resolved: number }, number | void>({
      query: (maxAgeHours) => ({
        url: `/incidents/resolve-stale${maxAgeHours ? `?max_age_hours=${maxAgeHours}` : ""}`,
        method: "POST",
      }),
      invalidatesTags: ["Incident"],
    }),
  }),
});

export const {
  useListIncidentsQuery,
  useReportIncidentMutation,
  useResolveIncidentMutation,
  useResolveStaleMutation,
} = incidentsApi;
