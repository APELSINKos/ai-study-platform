import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SessionOut } from "@/lib/api/types";

import { fetchCurrentUser, login, logout, register } from "./api";

export const CURRENT_USER_QUERY_KEY = ["auth", "me"] as const;

export function useCurrentUser() {
  return useQuery({
    queryKey: CURRENT_USER_QUERY_KEY,
    queryFn: fetchCurrentUser,
    retry: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: login,
    onSuccess: (session: SessionOut) => {
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, session.user);
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: register,
    onSuccess: (session: SessionOut) => {
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, session.user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
    },
  });
}
