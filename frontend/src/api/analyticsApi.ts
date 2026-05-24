import { baseApi } from "./baseApi";
import type {
  HeatmapResponse,
  IncidentStatsResponse,
  FleetEfficiencyResponse,
} from "../types";

interface TimeRangeParams {
  from: string;
  to: string;
}

export const analyticsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getHeatmap: build.query<HeatmapResponse, TimeRangeParams>({
      query: (params) => ({
        url: "/analytics/heatmap",
        params,
      }),
    }),
    getIncidentStats: build.query<IncidentStatsResponse, TimeRangeParams>({
      query: (params) => ({
        url: "/analytics/incidents",
        params,
      }),
    }),
    getFleetEfficiency: build.query<FleetEfficiencyResponse, TimeRangeParams>({
      query: (params) => ({
        url: "/analytics/efficiency",
        params,
      }),
    }),
  }),
});

export const {
  useGetHeatmapQuery,
  useGetIncidentStatsQuery,
  useGetFleetEfficiencyQuery,
} = analyticsApi;
