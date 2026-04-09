import React from "react";

export type StepStatus = "pending" | "loading" | "success" | "error";

export interface Step {
  label: string;
  status: StepStatus;
  message?: string;
}

interface ProgressStepsProps {
  steps: Step[];
  currentStep?: number;
}

const StepIcon: React.FC<{ status: StepStatus }> = ({ status }) => {
  switch (status) {
    case "pending":
      return (
        <div className="w-6 h-6 rounded-full border-2 border-gray-300 bg-white flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-gray-300" />
        </div>
      );
    case "loading":
      return (
        <div className="w-6 h-6 rounded-full border-2 border-blue-500 bg-white flex items-center justify-center">
          <svg
            className="animate-spin h-4 w-4 text-blue-500"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </div>
      );
    case "success":
      return (
        <div className="w-6 h-6 rounded-full bg-green-500 flex items-center justify-center">
          <svg
            className="w-4 h-4 text-white"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
        </div>
      );
    case "error":
      return (
        <div className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center">
          <svg
            className="w-4 h-4 text-white"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </div>
      );
  }
};

export const ProgressSteps: React.FC<ProgressStepsProps> = ({
  steps,
  currentStep,
}) => {
  return (
    <div className="space-y-4">
      {steps.map((step, index) => {
        const isActive = currentStep === index;
        const isPast = currentStep !== undefined && index < currentStep;

        return (
          <div key={index} className="relative">
            {/* 连接线 */}
            {index < steps.length - 1 && (
              <div
                className={`absolute left-3 top-6 w-0.5 h-8 ${
                  step.status === "success" || isPast
                    ? "bg-green-500"
                    : step.status === "error"
                    ? "bg-red-500"
                    : "bg-gray-300"
                }`}
              />
            )}

            {/* 步骤内容 */}
            <div className="flex items-start gap-3">
              {/* 状态图标 */}
              <div className="flex-shrink-0 mt-0.5">
                <StepIcon status={step.status} />
              </div>

              {/* 步骤信息 */}
              <div className="flex-1 min-w-0">
                <div
                  className={`font-medium ${
                    isActive
                      ? "text-blue-600"
                      : step.status === "success"
                      ? "text-green-600"
                      : step.status === "error"
                      ? "text-red-600"
                      : "text-gray-700"
                  }`}
                >
                  {step.label}
                </div>
                {step.message && (
                  <div
                    className={`text-sm mt-1 ${
                      step.status === "error"
                        ? "text-red-500"
                        : "text-gray-500"
                    }`}
                  >
                    {step.message}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
