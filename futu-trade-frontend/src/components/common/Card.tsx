// Card 组件

import { ReactNode } from "react";

interface CardProps {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  headerAction?: ReactNode;
}

export const Card = ({ title, subtitle, children, className = "", headerAction }: CardProps) => {
  return (
    <div className={`bg-card text-card-foreground border border-border rounded-lg shadow-sm overflow-hidden ${className}`}>
      {(title || subtitle || headerAction) && (
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div>
            {title && <h3 className="text-lg font-semibold text-foreground">{title}</h3>}
            {subtitle && <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          {headerAction && <div>{headerAction}</div>}
        </div>
      )}
      <div className="p-6">{children}</div>
    </div>
  );
};
