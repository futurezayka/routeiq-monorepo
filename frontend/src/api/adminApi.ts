import { baseApi } from "./baseApi";
import type { User } from "../types";

interface ResetResult {
  deleted_vehicles: number;
  deleted_incidents: number;
  deleted_routes: number;
  deleted_telemetry: number;
}

interface CreateUserRequest {
  email: string;
  password: string;
  full_name: string;
  role?: string;
}

export interface UsersPage {
  users: User[];
  total: number;
  offset: number;
  limit: number;
}

interface UsersQuery {
  page: number;
  per_page: number;
  role?: string;
  search?: string;
}

export const adminApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    resetSimulation: build.mutation<ResetResult, void>({
      query: () => ({ url: "/admin/reset-simulation", method: "POST" }),
      invalidatesTags: ["Vehicle", "Incident", "Route"],
    }),
    listUsers: build.query<UsersPage, UsersQuery>({
      query: ({ page, per_page, role, search }) => {
        const params = new URLSearchParams();
        params.set("page", String(page));
        params.set("per_page", String(per_page));
        if (role) params.set("role", role);
        if (search) params.set("search", search);
        return `/admin/users?${params}`;
      },
      providesTags: ["User"],
    }),
    createUser: build.mutation<User, CreateUserRequest>({
      query: (body) => ({ url: "/admin/users", method: "POST", body }),
      invalidatesTags: ["User"],
    }),
  }),
});

export const {
  useResetSimulationMutation,
  useListUsersQuery,
  useCreateUserMutation,
} = adminApi;
