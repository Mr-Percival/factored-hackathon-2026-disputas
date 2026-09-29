import { describe, expect, it } from "vitest";

import { routerBadge } from "@/lib/utils";

describe("routerBadge", () => {
  it("nombra el router que respondió el último turno, incluido el fallback", () => {
    expect(routerBadge(undefined).label).toBe("Sin LLM");
    expect(routerBadge("rules").label).toBe("Modo reglas (sin LLM)");
    expect(routerBadge("embed:char").label).toBe("Router aprendido (sin LLM)");
    expect(routerBadge("embed:char(rules:context)").label).toBe("Router aprendido (sin LLM)");
    expect(routerBadge("rules(fallback:model_unavailable)").label).toBe("Modo reglas (fallback)");
  });
});
