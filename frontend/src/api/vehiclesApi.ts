import { baseApi } from "./baseApi";
import type { Vehicle } from "../types";

export const vehiclesApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    listVehicles: build.query<Vehicle[], void>({
      query: () => "/vehicles",
      providesTags: ["Vehicle"],
    }),
  }),
});

export const { useListVehiclesQuery } = vehiclesApi;
