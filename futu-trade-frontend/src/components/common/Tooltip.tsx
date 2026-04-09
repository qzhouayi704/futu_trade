// 通用 Tooltip 组件 - 基于 Radix UI Tooltip

"use client";

import * as RadixTooltip from "@radix-ui/react-tooltip";
import { ReactNode } from "react";

interface TooltipProps {
    children: ReactNode;
    content: ReactNode;
    side?: "top" | "bottom" | "left" | "right";
    delayDuration?: number;
}

export function Tooltip({
    children,
    content,
    side = "top",
    delayDuration = 200,
}: TooltipProps) {
    return (
        <RadixTooltip.Provider delayDuration={delayDuration}>
            <RadixTooltip.Root>
                <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
                <RadixTooltip.Portal>
                    <RadixTooltip.Content
                        side={side}
                        sideOffset={6}
                        className="z-[100] max-w-xs rounded-lg border border-gray-600/50 bg-gray-800 px-3 py-2 text-xs leading-relaxed text-gray-200 shadow-xl backdrop-blur-sm animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
                    >
                        {content}
                        <RadixTooltip.Arrow className="fill-gray-800" />
                    </RadixTooltip.Content>
                </RadixTooltip.Portal>
            </RadixTooltip.Root>
        </RadixTooltip.Provider>
    );
}
