import { redirect } from "next/navigation";

/** The University Simulation dashboard opens on the Program Explorer. */
export default function UniversityIndex() {
  redirect("/university/programs");
}
