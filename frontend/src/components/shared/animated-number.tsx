"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useSpring, useTransform, useInView } from "framer-motion";
import { cn } from "@/lib/utils";

interface AnimatedNumberProps {
  value: number;
  duration?: number;
  formatFn?: (value: number) => string;
  className?: string;
  triggerOnView?: boolean;
}

export function AnimatedNumber({
  value,
  duration = 1,
  formatFn = (v) => v.toLocaleString(),
  className,
  triggerOnView = true,
}: AnimatedNumberProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });
  const [hasAnimated, setHasAnimated] = useState(false);

  const spring = useSpring(0, {
    duration: duration * 1000,
    bounce: 0,
  });

  const display = useTransform(spring, (current) => formatFn(current));

  useEffect(() => {
    if (triggerOnView) {
      if (isInView && !hasAnimated) {
        spring.set(value);
        setHasAnimated(true);
      }
    } else {
      spring.set(value);
    }
  }, [spring, value, isInView, triggerOnView, hasAnimated]);

  // Update value if it changes after initial animation
  useEffect(() => {
    if (hasAnimated) {
      spring.set(value);
    }
  }, [value, spring, hasAnimated]);

  return (
    <motion.span ref={ref} className={className}>
      {display}
    </motion.span>
  );
}

// Currency-specific animated number
interface AnimatedCurrencyProps {
  value: number;
  currency: string;
  duration?: number;
  className?: string;
  showSign?: boolean;
}

export function AnimatedCurrency({
  value,
  currency,
  duration = 1,
  className,
  showSign = false,
}: AnimatedCurrencyProps) {
  const formatCurrency = (v: number) => {
    const formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Math.abs(v));

    if (showSign && v > 0) {
      return `+${formatted}`;
    }
    if (v < 0) {
      return `-${formatted.replace("-", "")}`;
    }
    return formatted;
  };

  return (
    <AnimatedNumber
      value={value}
      duration={duration}
      formatFn={formatCurrency}
      className={className}
    />
  );
}

// Percentage-specific animated number
interface AnimatedPercentageProps {
  value: number; // Value as decimal (0.15 = 15%)
  duration?: number;
  className?: string;
  showSign?: boolean;
  decimals?: number;
}

export function AnimatedPercentage({
  value,
  duration = 1,
  className,
  showSign = true,
  decimals = 2,
}: AnimatedPercentageProps) {
  const formatPercentage = (v: number) => {
    const percentage = v * 100;
    const sign = showSign && percentage > 0 ? "+" : "";
    return `${sign}${percentage.toFixed(decimals)}%`;
  };

  return (
    <AnimatedNumber
      value={value}
      duration={duration}
      formatFn={formatPercentage}
      className={className}
    />
  );
}

// Counter that counts up from 0
interface CountUpProps {
  end: number;
  start?: number;
  duration?: number;
  delay?: number;
  className?: string;
  suffix?: string;
  prefix?: string;
}

export function CountUp({
  end,
  start = 0,
  duration = 2,
  delay = 0,
  className,
  suffix = "",
  prefix = "",
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isInView = useInView(ref, { once: true });
  const [displayValue, setDisplayValue] = useState(start);

  useEffect(() => {
    if (!isInView) return;

    const startTime = Date.now() + delay * 1000;
    const endTime = startTime + duration * 1000;

    const updateValue = () => {
      const now = Date.now();

      if (now < startTime) {
        requestAnimationFrame(updateValue);
        return;
      }

      if (now >= endTime) {
        setDisplayValue(end);
        return;
      }

      const progress = (now - startTime) / (duration * 1000);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + (end - start) * eased;

      setDisplayValue(Math.round(current));
      requestAnimationFrame(updateValue);
    };

    requestAnimationFrame(updateValue);
  }, [isInView, start, end, duration, delay]);

  return (
    <span ref={ref} className={className}>
      {prefix}
      {displayValue.toLocaleString()}
      {suffix}
    </span>
  );
}
