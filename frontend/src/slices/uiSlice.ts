import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type SelectedEntity =
  | { type: "vehicle"; id: string }
  | { type: "route"; id: string }
  | null;

interface UIState {
  selectedEntity: SelectedEntity;
}

const initialState: UIState = {
  selectedEntity: null,
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    selectVehicle(state, action: PayloadAction<string>) {
      const cur = state.selectedEntity;
      if (cur && cur.type === "vehicle" && cur.id === action.payload) {
        state.selectedEntity = null;
        return;
      }
      state.selectedEntity = { type: "vehicle", id: action.payload };
    },
    selectRoute(state, action: PayloadAction<string>) {
      const cur = state.selectedEntity;
      if (cur && cur.type === "route" && cur.id === action.payload) {
        state.selectedEntity = null;
        return;
      }
      state.selectedEntity = { type: "route", id: action.payload };
    },
    clearSelection(state) {
      state.selectedEntity = null;
    },
  },
});

export const { selectVehicle, selectRoute, clearSelection } = uiSlice.actions;
export default uiSlice.reducer;
