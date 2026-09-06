import type { HvBehavior } from "hyperview";

import { publishSnackbar } from "../feedback/snackbar";

const ShowSnackbarBehavior: HvBehavior = {
  action: "show-snackbar",
  callback: (element) => {
    const message = element.getAttribute("message")?.trim();
    if (!message) {
      return;
    }
    publishSnackbar({
      message,
      tone: element.getAttribute("tone") === "error" ? "error" : "success",
    });
  },
};

export default ShowSnackbarBehavior;
